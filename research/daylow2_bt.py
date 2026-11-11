"""日内"低点守住做多 / 高点压住做空"第二轮：换品种 + 顺大方向 + 顺小时趋势。
币：7个主流币 15分钟线（2022起），大方向 = 比特币50日线。 股票：AMD/美光/戴尔 美股时段1小时线（2020起），大方向 = 纳指(QQQ)200日线。
进场/止损同 daylow_bt.py：过去一天的最低价 L 守住 H 根K线、现价比 L 高 x%（分档）第一次满足时进，止损 L×(1-0.1%)。
出场 A：涨到 +2R 止损挪到 +1R，逐格上移（用户做法）；C：固定 +2R。成本往返 0.1%。
trend 列：进场时小时级趋势是否顺向（EMA20 与 EMA50，按1小时折算）。
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

COST = 0.001


def exit_trade(o, h, l, c, i, side, entry, stop, mode, maxhold):
    R = abs(entry - stop); best = entry; end = min(len(c) - 1, i + maxhold)
    for j in range(i + 1, end + 1):
        lo, hi = (l[j], h[j]) if side == 1 else (-h[j], -l[j])
        s = stop * side
        if lo <= s: return j, (o[j] if o[j] * side < s else stop)      # 跳空越过止损按开盘价成交
        if mode == "C" and hi >= entry * side + 2 * R: return j, entry + side * 2 * R
        if hi > best * side: best = hi * side
        k = (best * side - entry * side) / R
        if mode == "A" and k >= 2:
            ns = entry + side * (int(k) - 1) * R
            if ns * side > s: stop = ns
    return end, c[end]


def run(sym, d, bullD, W, perh, Hs, bands, grp):
    d = d.sort_values("ts").reset_index(drop=True)
    ts = d.ts.values; o, h, l, c = (d[k].values.astype(float) for k in ("open", "high", "low", "close"))
    bull = bullD.reindex(pd.DatetimeIndex(d.ts).tz_localize(None).floor("D"), method="ffill").values
    cs = pd.Series(c)
    up = (cs.ewm(span=int(20 * perh), adjust=False).mean() > cs.ewm(span=int(50 * perh), adjust=False).mean()).values
    rows = []
    for side in (1, -1):
        ext = pd.Series(l if side == 1 else -h)
        roll = ext.rolling(W).min().values
        idx = ext.rolling(W).apply(lambda x: W - 1 - np.argmin(x), raw=True).values
        for H in Hs:
            for x0, x1 in bands:
                ok = (idx >= H) & (c * side - roll >= np.abs(roll) * x0) & (c * side - roll < np.abs(roll) * x1)
                used = None; busy = {"A": -1, "C": -1}
                for i in np.flatnonzero(ok):
                    if roll[i] == used: continue
                    used = roll[i]
                    if bull[i] != bull[i]: continue
                    entry = c[i]; stop = roll[i] * side * (1 - side * 0.001); R = abs(entry - stop)
                    for m in "AC":
                        if i <= busy[m]: continue
                        j, px = exit_trade(o, h, l, c, i, side, entry, stop, m, 2 * W)
                        busy[m] = j
                        ret = side * (px / entry - 1) - COST
                        rows.append((grp, sym, side, H, x0, m, ts[i], bool(bull[i]), bool(up[i]) == (side == 1), ret * 500))
    return pd.DataFrame(rows, columns=["grp", "sym", "side", "H", "x0", "mode", "ts", "bull", "trend", "u"])


def dma(close, n):
    day = close.resample("1D").last().dropna()
    s = (day > day.rolling(n).mean()).shift(1)
    s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
    return s


out = []
btc = load.binance("1h", "BTCUSDT").set_index("ts").close
b50 = dma(btc, 50)
for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]:
    out.append(run(s, load.binance("15m", s), b50, 96, 4, (4, 12, 24), ((0.005, 0.01), (0.01, 0.02), (0.02, 0.035)), "coin"))
q = load.us_daily("QQQ", start="2018-01-01").set_index("date").adj_close
q200 = (q > q.rolling(200).mean()).shift(1)
for s in ["AMDUSUSD", "MUUSUSD", "DELLUSUSD"]:
    out.append(run(s, load.dukascopy(s), q200, 7, 1, (2, 4), ((0.005, 0.01), (0.01, 0.02), (0.02, 0.035)), "stock"))
t = pd.concat(out); t.to_csv("daylow2_trades.csv.gz", index=False)
t["ts"] = pd.to_datetime(t.ts)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)


def summ(g):
    mid = g.ts.sort_values().iloc[len(g) // 2]
    a, b = g[g.ts < mid], g[g.ts >= mid]
    return pd.Series({"n": len(g), "u": round(g.u.mean(), 2), "win%": round((g.u > 0).mean() * 100), "h1": round(a.u.mean(), 2),
                      "h2": round(b.u.mean(), 2), "t": round(g.u.mean() / g.u.std() * np.sqrt(len(g)), 1)})


print("== 品种组 × 方向 × 大方向 × 出场 =="); print(t.groupby(["grp", "side", "bull", "mode"]).apply(summ).to_string())
print("\n== 再加小时趋势是否顺向（出场A） =="); print(t[t["mode"] == "A"].groupby(["grp", "side", "bull", "trend"]).apply(summ).to_string())
print("\n== 顺大方向+顺小时趋势，分档（出场A） ==")
w = t[(t["mode"] == "A") & t.trend & (((t.side == 1) & t.bull) | ((t.side == -1) & ~t.bull))]
print(w.groupby(["grp", "side", "H", "x0"]).apply(summ).to_string())
print("\n== 同上，按品种 =="); print(w.groupby(["grp", "side", "sym"]).apply(summ).to_string())
