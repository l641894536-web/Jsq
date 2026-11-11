"""用户手法回测：金/银 "日内低点守住就做多，止损放低点下方，涨了把止损往上挪"（做空镜像：日内高点压住）。
5分钟线（Dukascopy，2020 起）。日内低点 = 过去24小时最低价。
进场：低点已经守住 H 小时，且现价比低点高 x%（x 落在某一档）时第一次满足，按收盘价进；每个低点只做一次。
止损：低点 × (1-0.1%)。R = 进场到止损的距离。成本往返 0.1%。最多拿 48 小时。
出场四种：
  A 阶梯上移（用户做法）：涨到 +2R 止损挪到 +1R，+3R 挪到 +2R ...
  B 到 +1R 保本，之后止损跟在最高价下方 1.5R
  C 固定 +2R 止盈
  D 只用初始止损，24小时后平
结果单位：100U 开 5 倍每次赚亏多少 U。
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

COST = 0.001
W = 288            # 24h of 5m bars
MAXHOLD = 576      # 48h


def exit_trade(h, l, c, i, side, entry, stop, mode):
    R = abs(entry - stop)
    best = entry
    n = len(c)
    end = min(n - 1, i + (288 if mode == "D" else MAXHOLD))
    for j in range(i + 1, end + 1):
        lo, hi = (l[j], h[j]) if side == 1 else (-h[j], -l[j])
        s = stop * side
        if lo <= s:
            return j, stop
        if mode == "C" and hi >= entry * side + 2 * R:
            return j, entry + side * 2 * R
        if hi > best * side:
            best = hi * side
        k = (best * side - entry * side) / R
        if mode == "A" and k >= 2:
            ns = entry + side * (int(k) - 1) * R
            if ns * side > s: stop = ns
        elif mode == "B" and k >= 1:
            ns = max(entry * side, best * side - 1.5 * R) * side
            if ns * side > s: stop = ns
    return end, c[end]


def run(sym):
    d = load.dukascopy(sym, interval="5m").sort_values("ts").reset_index(drop=True)
    ts = d.ts.values; o, h, l, c = (d[k].values.astype(float) for k in ("open", "high", "low", "close"))
    day = d.set_index("ts").close.resample("1D").last().dropna()
    bullD = (day > day.rolling(200).mean()).shift(1)
    bull = bullD.reindex(pd.DatetimeIndex(d.ts).floor("D")).values
    rows = []
    for side in (1, -1):
        ext = pd.Series(l if side == 1 else -h)
        roll = ext.rolling(W).min().values                      # 24h extreme (sign-adjusted)
        # bars since that extreme
        idx = ext.rolling(W).apply(lambda x: W - 1 - np.argmin(x), raw=True).values
        for H in (1, 3, 6):
            for x0, x1 in ((0.003, 0.006), (0.006, 0.010), (0.010, 0.016)):
                ok = (idx >= H * 12) & (c * side - roll >= np.abs(roll) * x0) & (c * side - roll < np.abs(roll) * x1)
                used = None; busy = {m: -1 for m in "ABCD"}
                for i in np.flatnonzero(ok):
                    key = (roll[i])
                    if key == used: continue                      # one trade per low
                    used = key
                    if bull[i] != bull[i]: continue
                    entry = c[i]; stop = roll[i] * side * (1 - side * 0.001)
                    R = abs(entry - stop)
                    for m in "ABCD":
                        if i <= busy[m]: continue
                        j, px = exit_trade(h, l, c, i, side, entry, stop, m)
                        busy[m] = j
                        ret = side * (px / entry - 1) - COST
                        rows.append((sym, side, H, x0, m, ts[i], bool(bull[i]), ret * 500, ret / (R / entry), (j - i) / 12,
                                     pd.Timestamp(ts[i]).hour))
    return pd.DataFrame(rows, columns=["sym", "side", "H", "x0", "mode", "ts", "bull", "u", "r", "hours", "hr"])


if __name__ == "__main__":
    t = pd.concat([run(s) for s in ("XAUUSD", "XAGUSD")])
    t.to_csv("daylow_trades.csv.gz", index=False)
    mid = pd.Timestamp("2023-06-01")
    t["half"] = np.where(pd.to_datetime(t.ts) < mid, 1, 2)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)

    def summ(g):
        return pd.Series({"n": len(g), "u": round(g.u.mean(), 2), "win%": round((g.u > 0).mean() * 100),
                          "h1": round(g[g.half == 1].u.mean(), 2), "h2": round(g[g.half == 2].u.mean(), 2),
                          "hrs": round(g.hours.mean(), 1), "t": round(g.u.mean() / g.u.std() * np.sqrt(len(g)), 1)})
    print("== 总览：品种 × 方向 × 牛熊 × 出场 =="); print(t.groupby(["sym", "side", "bull", "mode"]).apply(summ).to_string())
    print("\n== 做多 A出场：守住几小时 × 离低点多远 =="); print(t[(t["mode"] == "A")].groupby(["sym", "side", "bull", "H", "x0"]).apply(summ).to_string())
