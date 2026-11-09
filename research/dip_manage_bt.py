"""熊市 AMD/美光/戴尔 回调企稳做多（纳指前一天在跌）——进场后怎么管：
R0 规则：1R 后止损挪到开仓价；回到5天高点全平；最多10天
R1 1R 后止损挪到开仓价上方 0.46R（相当于用户 424.36 开、439 止损）
R2 1R 后改跟踪：止损 = max(开仓价, 最近3天最低价)；回到5天高点全平
R3 回到5天高点先平一半，剩下的跟踪3天最低价（不封顶），最多20天
R4 不设目标：1R 后跟踪3天最低价，最多20天
每次 100U×5倍（名义500U），扣 0.05%×2 和多单资金费 0.03%/天。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X, scale_in_bt as SI
START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
NOT, FEE, FUND = 500.0, 0.0005, 0.0003


def manage(o, h, l, c, k, E0, stop, top, bpd, mode):
    R = E0 - stop; n = len(c); w = 1.0; got = 0.0; armed = False
    L3 = pd.Series(l).rolling(3 * bpd).min().to_numpy()
    maxd = 20 if mode in ("R3", "R4") else 10
    for j in range(k + 1, min(n, k + 1 + maxd * bpd)):
        if l[j] <= E0 * 0.81: return -100.0, j
        if l[j] <= stop:
            px = min(o[j], stop); got += w * (px / E0 - 1); return fin(got, k, j, bpd), j
        if h[j] >= E0 + R: armed = True
        if armed:
            if mode == "R0": stop = max(stop, E0)
            elif mode == "R1": stop = max(stop, E0 + 0.46 * R)
            elif mode in ("R2", "R4"): stop = max(stop, E0, L3[j - 1] if j > 0 else stop)
        if mode == "R3" and w == 1.0 and h[j] >= top:
            got += 0.5 * (max(o[j], top) / E0 - 1); w = 0.5; stop = max(stop, E0); armed = True
        if mode == "R3" and w == 0.5: stop = max(stop, E0, L3[j - 1])
        if mode in ("R0", "R1", "R2") and h[j] >= top:
            got += w * (max(o[j], top) / E0 - 1); return fin(got, k, j, bpd), j
    j = min(n - 1, k + maxd * bpd); got += w * (c[j] / E0 - 1)
    return fin(got, k, j, bpd), j


def fin(g, k, j, bpd):
    return (g - FEE * 2 - FUND * (j - k) / bpd) * NOT


us = load.us_daily(["^NDX", "QQQ"]); us["date"] = pd.to_datetime(us.date)
px = us.pivot(index="date", columns="ticker", values="close")
up = (px["^NDX"] > px["^NDX"].shift(1)).astype(float)
bull = X.bull_daily(px["QQQ"])
st = load.dukascopy([s + "USUSD" for s in ["AMD", "MU", "DELL"]], start="2021-06")
rows = []
for sym, g in st.groupby("symbol"):
    g = g.sort_values("ts").reset_index(drop=True); bpd = 7; tz = "America/New_York"
    o, h, l, c = (g[x].to_numpy(float) for x in ["open", "high", "low", "close"])
    ts = pd.to_datetime(g.ts, utc=True); day = ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    sig = SI.daily_sigma(g, tz).reindex(day, method="ffill").to_numpy()
    bb = bull.reindex(day, method="ffill").to_numpy()
    pup = up.shift(1).reindex(day, method="ffill").to_numpy()      # 进场当天之前最近一个交易日纳指是否上涨
    H5 = pd.Series(h).shift(1).rolling(35).max().to_numpy(); H12 = pd.Series(h).shift(1).rolling(4).max().to_numpy()
    n, t = len(c), 36
    while t < n - 1:
        s = sig[t]
        if not (START <= ts[t] < END and np.isfinite(s) and np.isfinite(H5[t]) and c[t] <= H5[t] * np.exp(-2 * s) and bb[t] == 0):
            t += 1; continue
        top, lowest, k = H5[t], l[t], None
        for u in range(t, min(n, t + 35)):
            lowest = min(lowest, l[u])
            if u > t and c[u] > H12[u] and c[u] < top: k = u; break
        if k is None: t += 35; continue
        endmax = k
        if pup[k] == 0:
            E0, stop = c[k], lowest * np.exp(-0.3 * s); r = {}
            for m in ("R0", "R1", "R2", "R3", "R4"):
                r[m], e = manage(o, h, l, c, k, E0, stop, top, bpd, m); endmax = max(endmax, e)
            rows.append(dict(sym=sym[:-5], ts=ts[k], half="前段" if ts[k] < MID else "后段", **r))
        t = max(t + 1, endmax + 1)
T = pd.DataFrame(rows)
print("次数", len(T))
NM = {"R0": "规则：1R后保本，回5天高点全平", "R1": "1R后止损提到+0.46R（=你的439）", "R2": "1R后跟踪3天低点，回5天高点全平",
      "R3": "5天高点先平一半，剩下跟踪不封顶", "R4": "不设目标，1R后跟踪3天低点"}
for m, nm in NM.items():
    hm = T.groupby("half")[m].mean()
    print(f"{nm:<28} 平均 {T[m].mean():+6.1f}U  赚的比例 {(T[m] > 0).mean()*100:3.0f}%  前段 {hm.get('前段'):+6.1f} 后段 {hm.get('后段'):+6.1f}  合计 {T[m].sum():+7.0f}U")
