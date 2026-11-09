"""把"分批"放到右边：突破进场（结论卡的规则），亏钱的仓不加，赚钱了才加。每次 100U×5倍（满仓名义 500U）。
  P 金字塔：第1笔30%在突破；浮盈到1R（第1笔止损已挪到开仓价）再加30%；浮盈到2R再加40%。所有仓位共用一个止损：
           开始在24小时低点外，1R后挪到开仓价，之后跟着3天低点挪（同 F）。
  F 一次性100%在突破，出场同上（结论卡现在的做法）。
  F30 只开30%（试仓）不加。
扣：每次成交 0.05%（单边）、多单资金费 0.03%/天。只看做多（牛市不做空），按牛熊分开、前后两段。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X
from contract_bt import signals, BUF, MIN_RISK

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
NOTIONAL, FEE, FUND = 500.0, 0.0005, 0.0003


def run_one(df, L, bpd):
    df = df.sort_values("ts").reset_index(drop=True)
    LS, SS, CU, CD, HI, LO = signals(df, L, "breakout")
    LS, CD, LO = LS.to_numpy(), CD.to_numpy(), LO.to_numpy()
    LO3 = df["low"].rolling(3 * L).min().to_numpy()
    o, h, l, c = (df[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    ts = pd.to_datetime(df.ts, utc=True)
    ok = ((ts >= START) & (ts < END)).to_numpy()
    out, i, n = [], 60, len(c)
    while i < n - 1:
        if not (LS[i] and ok[i]):
            i += 1; continue
        E0 = c[i]; stop0 = LO[i] * (1 - BUF); R = E0 - stop0
        if not (MIN_RISK * E0 <= R <= 0.2 * E0):
            i += 1; continue
        res = {}
        for mode in ("P", "F", "F30"):
            fills = [(0.3 if mode != "F" else 1.0, E0)]
            stop, armed, j = stop0, False, i + 1
            while j < n:
                if l[j] <= stop:
                    px = min(o[j], stop); break
                if mode == "P":
                    if len(fills) == 1 and h[j] >= E0 + R:
                        fills.append((0.3, max(o[j], E0 + R)))
                    if len(fills) == 2 and h[j] >= E0 + 2 * R:
                        fills.append((0.4, max(o[j], E0 + 2 * R)))
                if h[j] >= E0 + R:
                    armed = True
                if armed:
                    stop = max(stop, E0, LO3[j] * (1 - BUF))
                if CD[j] or j - i >= 10 * bpd or j == n - 1:
                    px = c[j]; break
                j += 1
            w = sum(f for f, _ in fills)
            pnl = sum(f * (px / p - 1) for f, p in fills)
            cost = w * FEE * 2 + w * FUND * (j - i) / bpd
            res[mode] = dict(pnl=(pnl - cost) * NOTIONAL, w=w)
        out.append(dict(ts=ts.iloc[i], **{f"{k}_{m}": v for m, d in res.items() for k, v in d.items()}))
        i = j + 1
    return pd.DataFrame(out)


if __name__ == "__main__":
    us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    sets = []
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        sets.append((grp, dk[dk.symbol == sym], 24, 24, X.bull_daily(px[fut]), "America/New_York"))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = X.bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        sets.append(("加密(7币)", g, 24, 24, btc, "UTC"))
    st = load.dukascopy([s + "USUSD" for s in ["AMD", "MU", "DELL"]], start="2021-06")
    for sym, g in st.groupby("symbol"):
        sets.append(("AMD/美光/戴尔", g, 7, 7, X.bull_daily(px["QQQ"]), "America/New_York"))
    out = []
    for grp, g, L, bpd, bull, tz in sets:
        t = run_one(g[["ts", "open", "high", "low", "close"]], L, bpd)
        day = t.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
        bb = bull.reindex(day, method="ffill").to_numpy()
        t["env"] = np.where(pd.isna(bb), None, np.where(bb == 1, "牛市", "熊市"))
        out.append(t.assign(grp=grp))
    t = pd.concat(out, ignore_index=True); t = t[t.env.notna()]
    t["half"] = np.where(t.ts < MID, "前段", "后段")
    t.to_csv("pyramid_trades.csv", index=False)
    rows = []
    for (g, e), x in t.groupby(["grp", "env"]):
        for m, nm in [("F30", "只开30%试仓"), ("P", "赚了再加（30→60→100%）"), ("F", "一次性100%")]:
            hm = x.groupby("half")[f"pnl_{m}"].mean()
            rows.append(dict(品种=g, 环境=e, 做法=nm, 次数=len(x), 每次平均U=round(x[f"pnl_{m}"].mean(), 2), 前段=round(hm.get("前段"), 2), 后段=round(hm.get("后段"), 2),
                             赚的比例=round((x[f"pnl_{m}"] > 0).mean() * 100), 最差一次U=round(x[f"pnl_{m}"].min(), 1),
                             亏的平均U=round(x[f"pnl_{m}"][x[f"pnl_{m}"] <= 0].mean(), 1), 加满的比例=round((x[f"w_{m}"] >= .99).mean() * 100)))
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))
