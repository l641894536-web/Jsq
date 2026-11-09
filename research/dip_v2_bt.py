"""抄底改良版（每次 100U×5倍，满仓名义 500U，扣每次成交 0.05%、多单资金费 0.03%/天）。σ=最近20天日波动。
"跌够了"：1小时收盘比过去5天最高价低 D·σ（D = 2 / 3 / 4，按品种自己的波动算）。
  W 跌够就分批（用户的b）：跌到 Dσ 买30%；再跌 1.5σ 买30%；之后24小时内反弹 0.5σ（企稳）买40%，继续跌就不买；
                         止损进场前就定好：比第1笔再往下 3σ，全部一起走
  S 企稳再进、赚了再加（用户的a + 金字塔）：跌够以后，收盘站上前12根小时线的最高价（止跌企稳）→ 买30%；
                         止损：这波下跌的最低点再下 0.3σ；浮盈1R（止损挪到开仓价）加30%，2R 加40%
  F 企稳后一次买满100%（对照），止损同 S
离场（三种一样）：回到当初5天最高价全平；1R后止损挪到开仓价；最多拿10天。5倍爆仓线（均价往下19%）先到算爆仓。
美股合约用交易时段小时线：5天=35根，12根→4根。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X
import scale_in_bt as SI

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
NOTIONAL, FEE, FUND = 500.0, 0.0005, 0.0003


def run_sym(df, bpd, sig, tz, D):
    df = df.sort_values("ts").reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    ts = pd.to_datetime(df.ts, utc=True)
    day = ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    S = sig.reindex(day, method="ffill").to_numpy()
    n5 = 5 * bpd; k12 = 12 if bpd == 24 else 4
    H5 = pd.Series(h).shift(1).rolling(n5).max().to_numpy()
    H12 = pd.Series(h).shift(1).rolling(k12).max().to_numpy()
    ok = ((ts >= START) & (ts < END)).to_numpy()
    n, out, t = len(c), [], n5 + 1
    while t < n - 1:
        s = S[t]
        if not (ok[t] and np.isfinite(s) and np.isfinite(H5[t]) and c[t] <= H5[t] * np.exp(-D * s)):
            t += 1; continue
        top = H5[t]
        # 企稳点：之后（最多5天内）第一次收盘站上前12根最高价，且还在 top 下方
        lowest, k = l[t], None
        for u in range(t, min(n, t + n5)):
            lowest = min(lowest, l[u])
            if u > t and c[u] > H12[u] and c[u] < top:
                k = u; break
        res = {}
        # ---- W：跌够就分批
        p1 = c[t]; p2 = p1 * np.exp(-1.5 * s); stopW = p1 * np.exp(-3 * s)
        res["W"] = sim_scale(o, h, l, c, t, p1, p2, s, stopW, top, bpd)
        # ---- S / F：企稳再进
        if k is not None:
            E0 = c[k]; stop = lowest * np.exp(-0.3 * s)
            res["S"] = sim_pyr(o, h, l, c, k, E0, stop, top, bpd, pyramid=True)
            res["F"] = sim_pyr(o, h, l, c, k, E0, stop, top, bpd, pyramid=False)
        out.append(dict(ts=ts.iloc[t], **{f"{a}_{m}": v for m, d in res.items() for a, v in d.items()}))
        t = max(t + 1, max(d["end"] for d in res.values()) + 1)
    return pd.DataFrame(out)


def close_out(fills, px, j0, j, bpd, liq):
    w = sum(f for f, _ in fills); avg = sum(f * p for f, p in fills) / w
    if liq:
        return dict(pnl=-100.0 * w, liq=True, end=j, w=w)
    gross = w * (px / avg - 1)
    cost = w * FEE * 2 + w * FUND * (j - j0) / bpd
    return dict(pnl=(gross - cost) * NOTIONAL, liq=False, end=j, w=w)


def sim_scale(o, h, l, c, t, p1, p2, s, stop, top, bpd):
    fills = [(0.3, p1)]; t2 = None; got3 = dead3 = False; n = len(c); R = p1 - stop; armed = False
    for j in range(t + 1, min(n, t + 1 + 10 * bpd)):
        if t2 is None and l[j] <= p2:
            fills.append((0.3, min(o[j], p2))); t2 = j
        w = sum(f for f, _ in fills); avg = sum(f * p for f, p in fills) / w
        if l[j] <= avg * 0.81:
            return close_out(fills, None, t, j, bpd, True)
        if l[j] <= stop:
            return close_out(fills, min(o[j], stop), t, j, bpd, False)
        if t2 is not None and not got3 and not dead3:
            if l[j] <= p2 * np.exp(-s): dead3 = True
            elif c[j] >= p2 * np.exp(0.5 * s) and j - t2 <= bpd: fills.append((0.4, c[j])); got3 = True
            elif j - t2 > bpd: dead3 = True
        if h[j] >= top:
            return close_out(fills, top if o[j] < top else o[j], t, j, bpd, False)
        if not armed and h[j] >= avg + R:
            armed = True; stop = max(stop, avg)
    j = min(n - 1, t + 10 * bpd)
    return close_out(fills, c[j], t, j, bpd, False)


def sim_pyr(o, h, l, c, k, E0, stop, top, bpd, pyramid):
    R = E0 - stop; n = len(c)
    if not (R > 0):
        return dict(pnl=np.nan, liq=False, end=k, w=0)
    fills = [(0.3 if pyramid else 1.0, E0)]
    for j in range(k + 1, min(n, k + 1 + 10 * bpd)):
        w = sum(f for f, _ in fills); avg = sum(f * p for f, p in fills) / w
        if l[j] <= avg * 0.81:
            return close_out(fills, None, k, j, bpd, True)
        if l[j] <= stop:
            return close_out(fills, min(o[j], stop), k, j, bpd, False)
        if pyramid and len(fills) == 1 and h[j] >= E0 + R and E0 + R < top:
            fills.append((0.3, max(o[j], E0 + R)))
        if pyramid and len(fills) == 2 and h[j] >= E0 + 2 * R and E0 + 2 * R < top:
            fills.append((0.4, max(o[j], E0 + 2 * R)))
        if h[j] >= E0 + R:
            stop = max(stop, E0)
        if h[j] >= top:
            return close_out(fills, top if o[j] < top else o[j], k, j, bpd, False)
    j = min(n - 1, k + 10 * bpd)
    return close_out(fills, c[j], k, j, bpd, False)


if __name__ == "__main__":
    us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    sets = []
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        sets.append((grp, dk[dk.symbol == sym], 24, X.bull_daily(px[fut]), "America/New_York"))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = X.bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        sets.append(("币(BTC/ETH/SOL)", g, 24, btc, "UTC"))
    st = load.dukascopy([s + "USUSD" for s in ["AMD", "MU", "DELL"]], start="2021-06")
    for sym, g in st.groupby("symbol"):
        sets.append(("AMD/美光/戴尔", g, 7, X.bull_daily(px["QQQ"]), "America/New_York"))
    allt = []
    for D in (2, 3, 4):
        for grp, g, bpd, bull, tz in sets:
            t = run_sym(g[["ts", "open", "high", "low", "close"]], bpd, SI.daily_sigma(g, tz), tz, D)
            if t.empty:
                continue
            day = t.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
            bb = bull.reindex(day, method="ffill").to_numpy()
            t["env"] = np.where(pd.isna(bb), None, np.where(bb == 1, "牛市", "熊市"))
            allt.append(t.assign(grp=grp, D=D))
    T = pd.concat(allt, ignore_index=True); T = T[T.env.notna()]
    T["half"] = np.where(T.ts < MID, "前段", "后段")
    T.to_csv("dip_v2_trades.csv", index=False)
    NM = {"W": "跌够就分批(止损先定)", "S": "企稳再进+赚了再加", "F": "企稳后一次买满"}
    rows = []
    for (g, e, D), x in T.groupby(["grp", "env", "D"]):
        for m in ("W", "S", "F"):
            p = x[f"pnl_{m}"].dropna()
            if len(p) < 15:
                continue
            hm = x.dropna(subset=[f"pnl_{m}"]).groupby("half")[f"pnl_{m}"].mean()
            rows.append(dict(品种=g, 环境=e, 跌多少开始=f"{D}σ", 做法=NM[m], 次数=len(p), 每次平均U=round(p.mean(), 2), 合计U=round(p.sum()),
                             前段=round(hm.get("前段", np.nan), 2), 后段=round(hm.get("后段", np.nan), 2), 赚的比例=round((p > 0).mean() * 100),
                             最差一次U=round(p.min(), 1), 爆仓=int(x[f"liq_{m}"].fillna(False).astype(bool).sum())))
    pd.set_option("display.width", 260)
    R = pd.DataFrame(rows).sort_values(["环境", "品种", "跌多少开始", "做法"])
    R.to_csv("dip_v2_report.csv", index=False)
    print(R.to_string(index=False))
