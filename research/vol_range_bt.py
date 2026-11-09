"""按最近20天日波动估"接下来会走多远"，用历史校准：
  σ = 最近20个日收益（对数）的标准差（金银/大宗/股票只算工作日，加密算每天——和页面取币安日线的口径一样）
  1) 明天收盘、5天后收盘：实际涨跌 / (σ·√天数) 的 80% 区间该用几倍（正态是 1.28）
  2) 碰到概率：之后1天 / 5天里最高(最低)价离现价 ≥ k·σ·√天数 的比例（向上向下平均），k = 0.25 … 4
2021-11 → 2026-10，前后两段对比。"""
import sys, os, json
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np

E0, MID, E1 = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-01"), pd.Timestamp("2026-11-01")
KS = np.round(np.arange(0.25, 4.01, 0.25), 2)


def daily_from_hourly(g, weekdays):
    d = g.set_index("ts").resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    d.index = d.index.tz_localize(None)
    if weekdays:
        d = d[d.index.dayofweek < 5]
    return d


def rows_for(d):
    c, h, l = d.close.to_numpy(float), d.high.to_numpy(float), d.low.to_numpy(float)
    lr = np.r_[np.nan, np.diff(np.log(c))]
    sd = pd.Series(lr).rolling(20).std().to_numpy()
    out = []
    idx = d.index
    for t in np.where((idx >= E0) & (idx < E1))[0]:
        if t + 5 >= len(c) or not np.isfinite(sd[t]) or sd[t] <= 0:
            continue
        s1, s5 = sd[t], sd[t] * np.sqrt(5)
        out.append((idx[t], np.log(c[t + 1] / c[t]) / s1, np.log(c[t + 5] / c[t]) / s5,
                    np.log(h[t + 1] / c[t]) / s1, np.log(c[t] / l[t + 1]) / s1,
                    np.log(h[t + 1:t + 6].max() / c[t]) / s5, np.log(c[t] / l[t + 1:t + 6].min()) / s5, sd[t]))
    return out


def collect():
    data = {}
    dk = load.dukascopy(["XAUUSD", "XAGUSD", "XPTCMDUSD", "XPDCMDUSD", "COPPERCMDUSD", "GASCMDUSD"], start="2021-01")
    for sym, g in dk.groupby("symbol"):
        grp = {"XAUUSD": "gold", "XAGUSD": "silver"}.get(sym, "commod")
        data.setdefault(grp, []).extend(rows_for(daily_from_hourly(g, True)))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-01")
    for sym, g in cr.groupby("symbol"):
        data.setdefault("crypto", []).extend(rows_for(daily_from_hourly(g, False)))
    perps = [s[:-4] for s in json.load(open("perp_stocks.json"))]
    us = load.us_daily(perps, start="2021-01-01")
    nontech = {"JPM", "GS", "BAC", "BX", "V", "LLY", "UNH", "ABBV", "MRK", "PFE", "AMGN", "COST", "WMT", "HD", "MCD", "KO", "NKE",
               "DIS", "XOM", "OXY", "CAT", "ACN", "XLE", "SPY"}
    for sym, g in us.groupby("ticker"):
        d = g.set_index("date")[["high", "low", "close"]].dropna()
        grp = "stock_main" if sym in ("AMD", "MU", "DELL") else ("stock_nontech" if sym in nontech else "stock_other")
        data.setdefault(grp, []).extend(rows_for(d))
    cols = ["date", "z1", "z5", "u1", "d1", "u5", "d5", "sd"]
    return {k: pd.DataFrame(v, columns=cols) for k, v in data.items()}


def table(x):
    k80_1 = np.quantile(np.abs(x.z1), .8); k80_5 = np.quantile(np.abs(x.z5), .8)
    t1 = [float(((x.u1 >= k).mean() + (x.d1 >= k).mean()) / 2) for k in KS]
    t5 = [float(((x.u5 >= k).mean() + (x.d5 >= k).mean()) / 2) for k in KS]
    return dict(n=len(x), k80_1=round(float(k80_1), 3), k80_5=round(float(k80_5), 3), touch1=[round(p, 3) for p in t1], touch5=[round(p, 3) for p in t5])


if __name__ == "__main__":
    D = collect()
    out = {}
    for g, x in D.items():
        full = table(x)
        h1, h2 = table(x[x.date < MID]), table(x[x.date >= MID])
        out[g] = full
        i1, i2 = list(KS).index(1.0), list(KS).index(2.0)
        print(f"{g:14s} n={full['n']:6d}  80%区间倍数 明天 {full['k80_1']:.2f}（前{h1['k80_1']:.2f}/后{h2['k80_1']:.2f}）  5天 {full['k80_5']:.2f}（{h1['k80_5']:.2f}/{h2['k80_5']:.2f}）"
              f"  明天碰到1σ {full['touch1'][i1]:.2f}（{h1['touch1'][i1]:.2f}/{h2['touch1'][i1]:.2f}） 2σ {full['touch1'][i2]:.2f}"
              f"  5天碰到1σ√5 {full['touch5'][i1]:.2f} 2σ√5 {full['touch5'][i2]:.2f}")
    # 简单检验：用前半段的倍数，后半段实际覆盖多少
    print("\n用前半段校准的80%区间，在后半段实际罩住：")
    for g, x in D.items():
        a, b = x[x.date < MID], x[x.date >= MID]
        k1, k5 = np.quantile(np.abs(a.z1), .8), np.quantile(np.abs(a.z5), .8)
        print(f"  {g:14s} 明天 {(np.abs(b.z1) <= k1).mean()*100:.0f}%   5天 {(np.abs(b.z5) <= k5).mean()*100:.0f}%   （正态1.28倍：{(np.abs(b.z1) <= 1.2816).mean()*100:.0f}% / {(np.abs(b.z5) <= 1.2816).mean()*100:.0f}%）")
    json.dump(dict(ks=[float(k) for k in KS], groups=out), open("vol_range.json", "w"))
