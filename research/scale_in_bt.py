"""用户的分批抄底做法回测（每次 100U 保证金、5 倍 → 满仓名义 500U）：
  σ = 最近20天日波动（对数收益标准差）
  第1笔 30%：1小时收盘比过去24小时最高价跌了 1σ（"看到下跌觉得是买点"）
  第2笔 30%：之后继续跌到第1笔价格再往下 1σ（挂单成交）
  第3笔 40%：第2笔之后 24 小时内收盘反弹到第2笔价格上方 0.5σ（企稳）才进；如果先跌到第2笔再往下 1σ（继续跌）就不进
  离场：价格回到当初那个24小时最高价（反弹到位）全部平；或者到期（3天）平
  止损两种：A 硬抗（没有止损，只等3天）；B 统一止损：第2笔价格再往下 1.5σ，所有仓位一起走
对照：C 一次性 100% 在第1笔的位置买入，止损/止盈/到期同 B
扣：每次成交 0.05%（单边）、多单资金费 0.03%/天。2021-11 → 2026-10，按牛熊分开，前后两段。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
NOTIONAL, FEE, FUND = 500.0, 0.0005, 0.0003


def daily_sigma(g, tz):
    d = g.assign(day=g.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()).groupby("day").close.last()
    s = np.log(d).diff().rolling(20).std().shift(1)        # 只用昨天以前
    return s


def campaign(df, L, bpd, sig, tz):
    df = df.sort_values("ts").reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    ts = pd.to_datetime(df.ts, utc=True)
    day = ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    S = sig.reindex(day, method="ffill").to_numpy()
    H24 = pd.Series(h).shift(1).rolling(L).max().to_numpy()
    ok = ((ts >= START) & (ts < END)).to_numpy()
    n, out, t = len(c), [], L + 1
    maxbars = 3 * bpd
    while t < n - 1:
        s = S[t]
        if not (ok[t] and np.isfinite(s) and np.isfinite(H24[t]) and c[t] <= H24[t] * np.exp(-s)):
            t += 1; continue
        top = H24[t]; p1 = c[t]; p2 = p1 * np.exp(-s); stopB = p2 * np.exp(-1.5 * s); stopC = stopB
        res = {}
        for mode in ("A", "B", "C"):
            fills = [(0.3, p1)] if mode != "C" else [(1.0, p1)]
            got2 = mode == "C"; t2 = None; got3 = mode == "C"; dead3 = False
            exit_px, j = None, t + 1
            while j < n:
                stop = stopB if mode in ("B", "C") else None
                # 加仓（挂单价先成交，再看止损）
                if not got2 and l[j] <= p2:
                    px = min(o[j], p2); fills.append((0.3, px)); got2 = True; t2 = j
                if stop is not None and l[j] <= stop:
                    exit_px = min(o[j], stop); break
                if got2 and not got3 and not dead3 and mode != "C":
                    if l[j] <= p2 * np.exp(-s):
                        dead3 = True                               # 继续跌：第3笔不进
                    elif c[j] >= p2 * np.exp(0.5 * s) and j - t2 <= bpd:
                        fills.append((0.4, c[j])); got3 = True
                    elif j - t2 > bpd:
                        dead3 = True
                if h[j] >= top:
                    exit_px = max(o[j], top) if o[j] < top else o[j]; break
                if j - t >= maxbars or j == n - 1:
                    exit_px = c[j]; break
                j += 1
            w = sum(f for f, _ in fills)
            avg = sum(f * p for f, p in fills) / w
            gross = w * (exit_px / avg - 1)
            days = (j - t) / bpd
            cost = sum(f for f, _ in fills) * FEE * 2 + w * FUND * days
            worst = min(l[t + 1:j + 1].min() / avg - 1, 0) * w if j > t else 0   # 持仓期间最大浮亏（占满仓名义）
            res[mode] = dict(pnl=(gross - cost) * NOTIONAL, w=w, worst=worst * NOTIONAL, days=days,
                             win=gross - cost > 0, hit_top=exit_px >= top * 0.999)
        out.append(dict(ts=ts.iloc[t], **{f"{k}_{m}": v for m, d in res.items() for k, v in d.items()}))
        t = j + 1
    return pd.DataFrame(out)


def run():
    us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    sets = []
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        sets.append((grp, sym, dk[dk.symbol == sym], 24, 24, X.bull_daily(px[fut]), "America/New_York"))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = X.bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        sets.append(("加密(BTC/ETH/SOL)", sym, g, 24, 24, btc, "UTC"))
    st = load.dukascopy([s + "USUSD" for s in ["AMD", "MU", "DELL"]], start="2021-06")
    for sym, g in st.groupby("symbol"):
        sets.append(("AMD/美光/戴尔", sym, g, 7, 7, X.bull_daily(px["QQQ"]), "America/New_York"))
    out = []
    for grp, sym, g, L, bpd, bull, tz in sets:
        t = campaign(g[["ts", "open", "high", "low", "close"]], L, bpd, daily_sigma(g, tz), tz)
        day = t.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
        bb = bull.reindex(day, method="ffill").to_numpy()
        t["env"] = np.where(pd.isna(bb), None, np.where(bb == 1, "牛市", "熊市"))
        out.append(t.assign(grp=grp, sym=sym))
    t = pd.concat(out, ignore_index=True)
    t = t[t.env.notna()]
    t["half"] = np.where(t.ts < MID, "前段", "后段")
    return t


if __name__ == "__main__":
    t = run(); t.to_csv("scale_in_trades.csv", index=False)
    rows = []
    for (g, e), x in t.groupby(["grp", "env"]):
        for m, nm in [("A", "分批·硬抗3天"), ("B", "分批·统一止损"), ("C", "一次性·同样止损")]:
            hm = x.groupby("half")[f"pnl_{m}"].mean()
            rows.append(dict(品种=g, 环境=e, 做法=nm, 次数=len(x), 每次平均U=round(x[f"pnl_{m}"].mean(), 2), 前段=round(hm.get("前段", np.nan), 2),
                             后段=round(hm.get("后段", np.nan), 2), 赚的比例=round(x[f"win_{m}"].mean() * 100), 最差一次U=round(x[f"pnl_{m}"].min(), 1),
                             平均最大浮亏U=round(x[f"worst_{m}"].mean(), 1), 最大浮亏U=round(x[f"worst_{m}"].min(), 1),
                             三笔都进的比例=round((x[f"w_{m}"] >= 0.99).mean() * 100) if m != "C" else 100,
                             反弹到位比例=round(x[f"hit_top_{m}"].mean() * 100)))
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))
