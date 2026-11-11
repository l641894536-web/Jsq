"""熊市/横盘里能做什么（日线级别，拿几天）。分标的、分行情分别测，近5年（2021-11 起），前后两段。
标的组：黄金、白银（Dukascopy 小时线并成日线）、币（7个主流币，币安小时线并成日线）、指数（QQQ、SPY）、三只（AMD/美光/戴尔）、其他股票（美股日线库里其余个股）。
行情：big = 牛/熊（金银=自身200日线；币=比特币50日线；股票和指数=纳指QQQ 200日线；都用前一天）；
      st  = 横盘 / 有趋势（14日 ADX < 20 算横盘）。
打法（信号当天收盘进，成本往返0.1%，止损2倍日ATR，跳空越过止损按开盘价）：
  newlow_short  收盘创20日新低且在50日线下 → 做空，最多拿10天，收盘站回10日均线走
  newhigh_long  镜像（参照）
  oversold_long 从5日最高跌够2倍日波动（第一次）→ 做多，最多拿5天，回到5日均线走
  overbot_short 镜像
  range_long    价格落到20日区间最低20% → 做多，回到区间中间走，最多5天；range_short 镜像
  weak_short    （只对股票）每周一做空近60天最弱的20%，拿5天；strong_long 做多最强20%（参照）
单位：100U开5倍每次赚亏多少U。
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

COST, START = 0.001, pd.Timestamp("2021-11-01")
ETF = set("BITO DRAM EIDO EWJ EWT EWY EWZ EWZS GDX INTW IWM KORU KSTR LYTE MSTU MUU MVLL NVDL QQQ RAM SKDD SKUU SMH SNXX SOXL SOXS SQQQ TBT TMF TQQQ TSLL TZA URNM XBI XLE SPY".split())


def daily_from(df):
    d = df.set_index("ts")[["open", "high", "low", "close"]].resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    d.index = d.index.tz_localize(None); return d


def above(close, n):
    return (close > close.rolling(n).mean()).shift(1)


def adx(h, l, c, n=14):
    pc = c.shift(1); tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index); ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index)
    a = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi, ndi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a, 100 * ndm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), a


def sim(o, h, l, c, i, side, stop, maxd, exit_fn):
    for j in range(i + 1, min(len(c) - 1, i + maxd) + 1):
        lo, hi = (l[j], h[j]) if side == 1 else (-h[j], -l[j])
        if lo <= stop * side: return j, (o[j] if o[j] * side < stop * side else stop)
        if exit_fn(j): return j, c[j]
    j = min(len(c) - 1, i + maxd); return j, c[j]


def run(name, grp, d, big):
    d = d.dropna(); o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close")); n = len(c)
    C = d.close; ax, atr = adx(d.high, d.low, d.close); ax, atr = ax.to_numpy(), atr.to_numpy()
    bg = big.reindex(d.index, method="ffill").to_numpy()
    ma5, ma10, ma50 = (C.rolling(k).mean().to_numpy() for k in (5, 10, 50))
    lo20, hi20 = d.low.rolling(20).min(), d.high.rolling(20).max()
    pos = ((C - lo20) / (hi20 - lo20)).to_numpy(); mid = ((hi20 + lo20) / 2).to_numpy()
    lo20p, hi20p = C.rolling(20).min().shift(1).to_numpy(), C.rolling(20).max().shift(1).to_numpy()
    sg = np.log(C).diff().rolling(20).std().to_numpy()
    h5, l5 = d.high.rolling(5).max().to_numpy(), d.low.rolling(5).min().to_numpy()
    over = c <= h5 * np.exp(-2 * sg); overb = c >= l5 * np.exp(2 * sg)
    first = lambda x: x & ~np.r_[False, x[:-1]]
    sig = {
        "newlow_short": (-1, first((c < lo20p) & (c < ma50)), 10, lambda j: c[j] > ma10[j]),
        "newhigh_long": (1, first((c > hi20p) & (c > ma50)), 10, lambda j: c[j] < ma10[j]),
        "oversold_long": (1, first(over), 5, lambda j: c[j] > ma5[j]),
        "overbot_short": (-1, first(overb), 5, lambda j: c[j] < ma5[j]),
        "range_long": (1, first(pos <= 0.2), 5, lambda j: c[j] >= mid[j]),
        "range_short": (-1, first(pos >= 0.8), 5, lambda j: c[j] <= mid[j]),
    }
    rows = []
    for nm, (side, arr, maxd, ex) in sig.items():
        busy = -1
        for i in np.flatnonzero(arr):
            if i <= busy or i < 60 or d.index[i] < START or bg[i] != bg[i] or not np.isfinite(atr[i]): continue
            stop = c[i] - side * 2 * atr[i]
            j, px = sim(o, h, l, c, i, side, stop, maxd, ex); busy = j
            rows.append((grp, name, nm, d.index[i], bool(bg[i]), "横盘" if ax[i] < 20 else "有趋势", (side * (px / c[i] - 1) - COST) * 500, j - i))
    return rows


rows = []
for s, nm in (("XAUUSD", "黄金"), ("XAGUSD", "白银")):
    d = daily_from(load.dukascopy(s)); d = d[d.index.dayofweek < 5]
    rows += run(nm, nm, d, above(d.close, 200))
btc = daily_from(load.binance("1h", "BTCUSDT")); b50 = above(btc.close, 50)
for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]:
    rows += run(s[:-4], "币", daily_from(load.binance("1h", s)), b50)
U = load.us_daily(start="2020-06-01")
f = U.adj_close / U.close
for k in ("open", "high", "low", "close"): U[k] = U[k] * f
q = U[U.ticker == "QQQ"].set_index("date").close; q200 = above(q, 200)
THREE = {"AMD", "MU", "DELL"}
for tk, g in U.groupby("ticker"):
    if "=" in tk or "^" in tk or "-" in tk or len(g) < 400: continue
    if tk in ("QQQ", "SPY"): grp = "指数"
    elif tk in ETF: continue
    else: grp = "三只" if tk in THREE else "其他股票"
    rows += run(tk, grp, g.set_index("date")[["open", "high", "low", "close"]], q200)
T = pd.DataFrame(rows, columns=["grp", "inst", "method", "ts", "big", "st", "u", "days"])

# 横截面：每周一做空最弱20% / 做多最强20%（只对个股）
P = U[~U.ticker.isin(ETF) & ~U.ticker.str.contains(r"[=^-]")].pivot(index="date", columns="ticker", values="close").sort_index()
mom = P / P.shift(60) - 1; fwd = P.shift(-5) / P - 1
xs = []
for dte in P.index[(P.index >= START) & (P.index.dayofweek == 0)]:
    m = mom.loc[dte].dropna(); fw = fwd.loc[dte].reindex(m.index).dropna(); m = m.reindex(fw.index)
    if len(m) < 50 or q200.get(dte) != q200.get(dte): continue
    lo, hi = m <= m.quantile(0.2), m >= m.quantile(0.8)
    xs.append((dte, bool(q200.get(dte)), (-fw[lo].mean() - COST) * 500, (fw[hi].mean() - COST) * 500, (-fw.mean() - COST) * 500, (-fw[lo]).min() * 500))
X = pd.DataFrame(xs, columns=["ts", "big", "weak_short", "strong_long", "short_all", "worst_one"])
T.to_csv("bear_range_trades.csv.gz", index=False); X.to_csv("bear_range_xs.csv", index=False)

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
mid = pd.Timestamp("2024-05-01")


def summ(g):
    a, b = g[g.ts < mid].u, g[g.ts >= mid].u
    return pd.Series({"n": len(g), "u": round(g.u.mean(), 2), "win%": round((g.u > 0).mean() * 100), "h1": round(a.mean(), 2), "h2": round(b.mean(), 2), "n1": len(a), "n2": len(b),
                      "最差5%": round(g.u.quantile(0.05), 1), "天": round(g.days.mean(), 1), "t": round(g.u.mean() / g.u.std() * np.sqrt(len(g)), 1) if len(g) > 2 else 0})


T["big"] = T.big.map({True: "牛", False: "熊"})
R = T.groupby(["grp", "big", "st", "method"]).apply(summ).reset_index(); R.to_csv("bear_range_report.csv", index=False)
print("== 全表（组 × 牛熊 × 横盘/趋势 × 打法）=="); print(R.to_string(index=False))
ok = R[(R.n >= 60) & (R.h1 > 0) & (R.h2 > 0) & (R.t >= 2.5) & (R.n1 >= 20) & (R.n2 >= 20)].sort_values("t", ascending=False)
print("\n== 过关（前后两段都赚、t>=2.5）：共 %d 格里 %d 格 ==" % (len(R), len(ok))); print(ok.to_string(index=False))
R2 = T.groupby(["grp", "big", "method"]).apply(summ).reset_index()
print("\n== 不分横盘/趋势 =="); print(R2[R2.big == "熊"].to_string(index=False))
print("\n== 每周一做空最弱20%（个股，拿5天）=="); X["half"] = np.where(X.ts < mid, 1, 2)
for b, g in X.groupby("big"):
    print("牛" if b else "熊", len(g), "周：做空最弱", round(g.weak_short.mean(), 2), "(前后", round(g[g.half == 1].weak_short.mean(), 2), round(g[g.half == 2].weak_short.mean(), 2), ") 做空全部", round(g.short_all.mean(), 2),
          " 做多最强", round(g.strong_long.mean(), 2), " 最差一周", round(g.weak_short.min(), 1), " 单只最差", round(g.worst_one.min(), 0))
