"""日内方法总表：标的 × 行情 × 方法 × 方向，分别回测。
标的：黄金、白银（Dukascopy 5分钟并成15分钟，2020起）；7个主流币（币安15分钟，2022起）；AMD/美光/戴尔（美股时段1小时线，2020起）。
行情：大方向 big（金银=自身200日线；币=比特币50日线；股票=纳指200日线，都用前一天收盘）
      × 小时状态 st（up: 小时EMA20>EMA50 且价在EMA50上；down: 反之；flat: 其余）。
方法（做多/做空镜像）：brk4h 突破前4小时高低点；brk24h 突破前24小时（股票=前一个交易日长度）；lowhold 日内低点守住3小时后回升0.5~2%；
  rsi_rev RSI上穿30做多/下穿70做空；rsi_mom RSI上穿60做多/下穿40做空；boll_rev 跌出布林下轨后收回；boll_brk 收盘站上布林上轨；
  macd 柱子翻正/翻负；ema_pull 小时趋势向上时回踩小时EMA20收回；orb 伦敦/纽约开盘第一小时区间突破（股票=当天第一根）；pdh 突破昨天高/低点。
统一止损：1.5倍小时ATR（不小于0.3%）。出场 A：+2R后止损逐格上移，最多拿一天；出场 T：4小时到点就走。跳空越过止损按开盘价。成本往返0.1%。
单位：100U开5倍每次赚亏多少U。
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

COST = 0.001


def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values


def crossed_up(a, b):
    r = np.zeros(len(a), bool); r[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1]); return r


def sim(o, h, l, c, i, side, R, mode, maxhold):
    entry = c[i]; stop = entry - side * R; best = entry; end = min(len(c) - 1, i + maxhold)
    for j in range(i + 1, end + 1):
        lo, hi = (l[j], h[j]) if side == 1 else (-h[j], -l[j])
        s = stop * side
        if lo <= s: return j, (o[j] if o[j] * side < s else stop)
        if mode == "A":
            if hi > best * side: best = hi * side
            k = (best * side - entry * side) / R
            if k >= 2:
                ns = entry + side * (int(k) - 1) * R
                if ns * side > s: stop = ns
    return end, c[end]


def run(name, grp, d, bigD, bph, D, is_stock):
    d = d.sort_values("ts").reset_index(drop=True)
    ts = pd.DatetimeIndex(d.ts); o, h, l, c = (d[k].values.astype(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    tsn = ts.tz_localize(None) if ts.tz is not None else ts
    big = bigD.reindex(tsn.floor("D"), method="ffill").values
    e20, e50 = ema(c, 20 * bph), ema(c, 50 * bph)
    st = np.where((e20 > e50) & (c > e50), 1, np.where((e20 < e50) & (c < e50), -1, 0))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).rolling(14 * bph).mean().values * np.sqrt(bph)        # ≈ 小时ATR
    Rv = np.maximum(1.5 * atr, 0.003 * c)
    S = pd.Series
    sig = {}

    def both(nm, L, Sh): sig[nm] = (L, Sh)
    for nm, w in (("brk4h", 4 * bph), ("brk24h", D)):
        hh = S(h).rolling(w).max().shift(1).values; ll = S(l).rolling(w).min().shift(1).values
        both(nm, crossed_up(c, hh), crossed_up(-c, -ll))
    # lowhold
    def hold(ext):
        roll = ext.rolling(D).min().values
        idx = ext.rolling(D).apply(lambda x: D - 1 - np.argmin(x), raw=True).values
        cc = c if ext is exL else -c
        ok = (idx >= 3 * bph) & (cc - roll >= abs(roll) * 0.005) & (cc - roll < abs(roll) * 0.02)
        out = np.zeros(n, bool); used = None
        for i in np.flatnonzero(ok):
            if roll[i] != used: out[i] = True; used = roll[i]
        return out
    exL, exH = S(l), S(-h)
    both("lowhold", hold(exL), hold(exH))
    # RSI
    dlt = np.diff(c, prepend=c[0]); up = S(np.clip(dlt, 0, None)).ewm(alpha=1 / 14, adjust=False).mean(); dn = S(np.clip(-dlt, 0, None)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).values
    k = lambda v: np.full(n, float(v))
    both("rsi_rev", crossed_up(rsi, k(30)), crossed_up(-rsi, k(-70)))
    both("rsi_mom", crossed_up(rsi, k(60)), crossed_up(-rsi, k(-40)))
    # Bollinger
    m = S(c).rolling(20).mean().values; sd = S(c).rolling(20).std().values; ub, lb = m + 2 * sd, m - 2 * sd
    both("boll_rev", crossed_up(c, lb), crossed_up(-c, -ub))
    both("boll_brk", crossed_up(c, ub), crossed_up(-c, -lb))
    # MACD
    hist = (ema(c, 12) - ema(c, 26)); hist = hist - ema(hist, 9)
    both("macd", crossed_up(hist, k(0)), crossed_up(-hist, k(0)))
    # EMA pullback (小时EMA20)
    both("ema_pull", (st == 1) & (l <= e20) & (c > e20) & (pc > e20), (st == -1) & (h >= e20) & (c < e20) & (pc < e20))
    # ORB
    L = np.zeros(n, bool); Sh = np.zeros(n, bool)
    if is_stock:
        dayid = tsn.floor("D").values; first = np.r_[True, dayid[1:] != dayid[:-1]]
        rh = rl = np.nan; done = True
        for i in range(n):
            if first[i]: rh, rl, done = h[i], l[i], False
            elif not done:
                if c[i] > rh: L[i] = True; done = True
                elif c[i] < rl: Sh[i] = True; done = True
    else:
        hr = tsn.hour.values; mn = tsn.minute.values
        i = 0
        while i < n - 20:
            if (hr[i] in (7, 13)) and mn[i] == 0:
                rh, rl = h[i:i + 4].max(), l[i:i + 4].min()
                for j in range(i + 4, i + 20):
                    if c[j] > rh: L[j] = True; break
                    if c[j] < rl: Sh[j] = True; break
                i += 20
            else: i += 1
    both("orb", L, Sh)
    # 昨日高低
    dd = pd.DataFrame({"h": h, "l": l}, index=tsn).groupby(tsn.floor("D")).agg(h=("h", "max"), l=("l", "min")).shift(1)
    ph = dd.h.reindex(tsn.floor("D")).values; pl = dd.l.reindex(tsn.floor("D")).values
    both("pdh", crossed_up(c, ph), crossed_up(-c, -pl))

    rows = []
    maxA = D if not is_stock else 2 * D
    for nm, (Ls, Ss) in sig.items():
        for side, arr in ((1, Ls), (-1, Ss)):
            for mode, mh in (("A", maxA), ("T", 4 * bph)):
                busy = -1
                for i in np.flatnonzero(arr):
                    if i <= busy or i < 60 * bph or big[i] != big[i] or Rv[i] != Rv[i]: continue
                    j, px = sim(o, h, l, c, i, side, Rv[i], mode, mh); busy = j
                    rows.append((grp, name, nm, side, mode, ts[i], bool(big[i]), int(st[i]), (side * (px / c[i] - 1) - COST) * 500))
    return pd.DataFrame(rows, columns=["grp", "inst", "method", "side", "exit", "ts", "big", "st", "u"])


def dma(close, n):
    day = close.resample("1D").last().dropna(); s = (day > day.rolling(n).mean()).shift(1)
    if s.index.tz is not None: s.index = s.index.tz_localize(None)
    return s


if __name__ == "__main__":
    out = []
    for s, nm in (("XAUUSD", "黄金"), ("XAGUSD", "白银")):
        d5 = load.dukascopy(s, interval="5m").set_index("ts")
        d = d5.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
        out.append(run(nm, nm, d, dma(d.set_index("ts").close, 200), 4, 92, False)); print(nm, len(out[-1]), flush=True)
    b50 = dma(load.binance("1h", "BTCUSDT").set_index("ts").close, 50)
    for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]:
        out.append(run(s[:-4], "币", load.binance("15m", s), b50, 4, 96, False)); print(s, len(out[-1]), flush=True)
    q = load.us_daily("QQQ", start="2018-01-01").set_index("date").adj_close; q200 = (q > q.rolling(200).mean()).shift(1)
    for s, nm in (("AMDUSUSD", "AMD"), ("MUUSUSD", "美光"), ("DELLUSUSD", "戴尔")):
        out.append(run(nm, "股票", load.dukascopy(s), q200, 1, 7, True)); print(nm, len(out[-1]), flush=True)
    t = pd.concat(out); t.to_csv("intraday_grid_trades.csv.gz", index=False); print("trades", len(t))
