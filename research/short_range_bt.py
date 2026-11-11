"""空头打法 + 震荡横盘打法，系统回测（日线；金银和币另加4小时线）。近5年（2021-11 起），分标的、分牛熊、分横盘/有趋势。
标的组：黄金、白银、币（7个主流币）、指数（QQQ/SPY）、三只（AMD/美光/戴尔）、其他股票。
行情：big 牛/熊（金银=自身200日线；币=比特币50日线；股票/指数=纳指200日线；前一天）；st 横盘（14根ADX<20）/有趋势。
成本往返0.1%，止损2倍ATR（跳空越过按开盘价），信号K线收盘进。单位：100U开5倍每次赚亏多少U。

一、过热之后等第一下转弱再做空（_S；镜像 _L = 超跌后第一下转强做多）  出场：回到20均线，或8根K线
  heat_ext  离20均线超过2.5倍标准差        heat_rsi  RSI14 到过75以上（做多：25以下）
  heat_run  连涨5根以上                    heat_para 10根涨幅超过3倍正常波动
  heat_vol  放3倍量冲到20根新高（只有带成交量的品种）
  "第一下转弱" = 过热出现后3根K线内，收盘跌破前一根最低价。
二、顺着下跌做空（_S；镜像 _L）  出场：收盘站回10均线，或15根K线
  fail_rally 50均线向下，价格弹到20均线附近又收在20均线下方并跌破前一根低点
  lower_high 创20根新低后反弹超过1.5倍ATR，再跌破前一根低点（更低的高点）
  gap_dn     放量（3倍）跳空大跌5%以上，收盘做空拿20根（只对股票；镜像 gap_up）
三、震荡打法
  bb_rev    跌出布林下轨后收回 → 做多到中轨（镜像做空）        rsi2  RSI2<=5 做多 / >=95 做空，回5均线走
  fakeout   突破20根高点后1~2根内又收回来 → 反手做空（镜像）     edge  到区间上沿20%且跌破前一根低点 → 做空到区间中间（镜像）
  squeeze   布林带宽度缩到120根最窄之后的突破，顺突破方向做，按10均线出
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

COST, START = 0.001, pd.Timestamp("2021-11-01")
ETF = set("BITO DRAM EIDO EWJ EWT EWY EWZ EWZS GDX INTW IWM KORU KSTR LYTE MSTU MUU MVLL NVDL QQQ RAM SKDD SKUU SMH SNXX SOXL SOXS SQQQ TBT TMF TQQQ TSLL TZA URNM XBI XLE SPY".split())


def bars_from(df, rule):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df: agg["volume"] = "sum"
    d = df.set_index("ts")[list(agg)].resample(rule).agg(agg).dropna(subset=["close"])
    d.index = d.index.tz_localize(None); return d


def above(close, n): return (close > close.rolling(n).mean()).shift(1)


def adx_atr(h, l, c, n=14):
    pc = c.shift(1); tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index); ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index)
    a = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi, ndi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a, 100 * ndm.ewm(alpha=1 / n, adjust=False).mean() / a
    return (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).ewm(alpha=1 / n, adjust=False).mean().to_numpy(), a.to_numpy()


def rsi(c, n):
    d = c.diff(); u = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + u / dn.replace(0, np.nan))).fillna(50).to_numpy()


def recent(x, k=3):          # x 在前 k 根（不含当前）内出现过
    s = pd.Series(x.astype(float)); return (s.shift(1).rolling(k, min_periods=1).max().fillna(0) > 0).to_numpy()


def first(x): return x & ~np.r_[False, x[:-1]]


def sim(o, h, l, c, i, side, stop, maxb, ex):
    last = min(len(c) - 1, i + maxb)
    for j in range(i + 1, last + 1):
        lo, hi = (l[j], h[j]) if side == 1 else (-h[j], -l[j])
        if lo <= stop * side: return j, (o[j] if o[j] * side < stop * side else stop)
        if ex is not None and ex(j): return j, c[j]
    return last, c[last]


def run(name, grp, tf, d, big, big_idx_daily=True):
    d = d.dropna(subset=["open", "high", "low", "close"]); n = len(d)
    if n < 300: return []
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close")); C = d.close
    v = d.volume.to_numpy(float) if "volume" in d and d.volume.notna().sum() > 200 and (d.volume > 0).mean() > 0.9 else None
    ax, atr = adx_atr(d.high, d.low, C)
    bg = big.reindex(d.index.floor("D"), method="ffill").to_numpy()
    ma5, ma10, ma20, ma50 = (C.rolling(k).mean().to_numpy() for k in (5, 10, 20, 50)); sd20 = C.rolling(20).std().to_numpy()
    r14, r2 = rsi(C, 14), rsi(C, 2)
    ph, pl, pc = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]], np.r_[np.nan, c[:-1]]
    crackD, crackU = c < pl, c > ph
    lr = np.log(C).diff(); sg = lr.rolling(20).std().to_numpy()
    z = (c - ma20) / sd20
    upr = (C.diff() > 0).astype(int); run_up = upr.groupby((upr == 0).cumsum()).cumsum().to_numpy()
    dnr = (C.diff() < 0).astype(int); run_dn = dnr.groupby((dnr == 0).cumsum()).cumsum().to_numpy()
    g10 = np.log(C / C.shift(10)).to_numpy(); para_u, para_d = g10 >= 3 * sg * np.sqrt(10), g10 <= -3 * sg * np.sqrt(10)
    hi20c, lo20c = C.rolling(20).max().shift(1).to_numpy(), C.rolling(20).min().shift(1).to_numpy()
    hi20, lo20 = d.high.rolling(20).max().to_numpy(), d.low.rolling(20).min().to_numpy()
    pos = (c - lo20) / (hi20 - lo20); mid = (hi20 + lo20) / 2
    ub, lb = ma20 + 2 * sd20, ma20 - 2 * sd20
    bw = pd.Series(sd20 / ma20); sq = recent((bw <= bw.rolling(120).min() * 1.05).to_numpy(), 5)
    ma50dn, ma50up = ma50 < np.r_[[np.nan] * 10, ma50[:-10]], ma50 > np.r_[[np.nan] * 10, ma50[:-10]]
    # lower high / higher low
    newlo, newhi = c < lo20c, c > hi20c
    lowS = pd.Series(np.where(newlo, l, np.nan)).ffill(limit=15).to_numpy(); highS = pd.Series(np.where(newhi, h, np.nan)).ffill(limit=15).to_numpy()
    bounced = recent((h - lowS) >= 1.5 * atr, 8); dipped = recent((highS - l) >= 1.5 * atr, 8)
    REV = ("rev", 8); TR = ("trend", 15)
    S = {
        "heat_ext_S": (-1, recent(z >= 2.5) & crackD, REV), "heat_ext_L": (1, recent(z <= -2.5) & crackU, REV),
        "heat_rsi_S": (-1, recent(r14 >= 75) & crackD, REV), "heat_rsi_L": (1, recent(r14 <= 25) & crackU, REV),
        "heat_run_S": (-1, recent(run_up >= 5, 1) & (c < pc), REV), "heat_run_L": (1, recent(run_dn >= 5, 1) & (c > pc), REV),
        "heat_para_S": (-1, recent(para_u) & crackD, REV), "heat_para_L": (1, recent(para_d) & crackU, REV),
        "fail_rally_S": (-1, ma50dn & (h >= ma20) & (c < ma20) & crackD, TR), "fail_rally_L": (1, ma50up & (l <= ma20) & (c > ma20) & crackU, TR),
        "lower_high_S": (-1, bounced & crackD & (c > lowS) & ~newlo, TR), "lower_high_L": (1, dipped & crackU & (c < highS) & ~newhi, TR),
        "bb_rev_S": (-1, (pc > np.r_[np.nan, ub[:-1]]) & (c < ub), REV), "bb_rev_L": (1, (pc < np.r_[np.nan, lb[:-1]]) & (c > lb), REV),
        "rsi2_S": (-1, r2 >= 95, ("ma5", 5)), "rsi2_L": (1, r2 <= 5, ("ma5", 5)),
        "fakeout_S": (-1, recent(newhi, 2) & (c < np.r_[np.nan, hi20c[:-1]]) & (c < pc), REV), "fakeout_L": (1, recent(newlo, 2) & (c > np.r_[np.nan, lo20c[:-1]]) & (c > pc), REV),
        "edge_S": (-1, (pos >= 0.8) & crackD, ("mid", 8)), "edge_L": (1, (pos <= 0.2) & crackU, ("mid", 8)),
        "squeeze_S": (-1, sq & newlo, TR), "squeeze_L": (1, sq & newhi, TR),
    }
    if v is not None:
        va = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
        S["heat_vol_S"] = (-1, recent((v >= 3 * va) & newhi) & crackD, REV); S["heat_vol_L"] = (1, recent((v >= 3 * va) & newlo) & crackU, REV)
        if tf == "日线" and grp in ("三只", "其他股票", "指数"):
            gap = o / pc - 1
            S["gap_dn_S"] = (-1, (gap <= -0.05) & (v >= 3 * va) & (c < pc), ("hold", 20)); S["gap_up_L"] = (1, (gap >= 0.05) & (v >= 3 * va) & (c > pc), ("hold", 20))
    rows = []
    for nm, (side, arr, (ek, maxb)) in S.items():
        arr = first(np.nan_to_num(arr.astype(float)) > 0); busy = -1
        ex = {"rev": (lambda j: c[j] <= ma20[j]) if side == -1 else (lambda j: c[j] >= ma20[j]),
              "trend": (lambda j: c[j] > ma10[j]) if side == -1 else (lambda j: c[j] < ma10[j]),
              "ma5": (lambda j: c[j] < ma5[j]) if side == -1 else (lambda j: c[j] > ma5[j]),
              "mid": (lambda j: c[j] <= mid[j]) if side == -1 else (lambda j: c[j] >= mid[j]), "hold": None}[ek]
        for i in np.flatnonzero(arr):
            if i <= busy or i < 130 or d.index[i] < START or bg[i] != bg[i] or not np.isfinite(atr[i]) or atr[i] <= 0: continue
            j, px = sim(o, h, l, c, i, side, c[i] - side * 2 * atr[i], maxb, ex); busy = j
            rows.append((grp, tf, name, nm, d.index[i], bool(bg[i]), "横盘" if ax[i] < 20 else "有趋势", (side * (px / c[i] - 1) - COST) * 500, 2 * atr[i] / c[i]))
    return rows


if __name__ == "__main__":
    rows = []
    for s, nm in (("XAUUSD", "黄金"), ("XAGUSD", "白银")):
        raw = load.dukascopy(s); dd = bars_from(raw, "1D"); dd = dd[dd.index.dayofweek < 5]; bg = above(dd.close, 200)
        rows += run(nm, nm, "日线", dd.drop(columns=["volume"], errors="ignore"), bg); rows += run(nm, nm, "4小时", bars_from(raw, "4h").drop(columns=["volume"], errors="ignore"), bg)
    braw = load.binance("1h", "BTCUSDT"); b50 = above(bars_from(braw, "1D").close, 50)
    for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]:
        raw = load.binance("1h", s); rows += run(s[:-4], "币", "日线", bars_from(raw, "1D"), b50); rows += run(s[:-4], "币", "4小时", bars_from(raw, "4h"), b50)
    print("metals+coins", len(rows), flush=True)
    U = load.us_daily(start="2020-06-01"); f = U.adj_close / U.close
    for k in ("open", "high", "low", "close"): U[k] = U[k] * f
    q = U[U.ticker == "QQQ"].set_index("date").close; q200 = above(q, 200)
    for tk, g in U.groupby("ticker"):
        if "=" in tk or "^" in tk or "-" in tk or len(g) < 400: continue
        if tk in ("QQQ", "SPY"): grp = "指数"
        elif tk in ETF: continue
        else: grp = "三只" if tk in {"AMD", "MU", "DELL"} else "其他股票"
        rows += run(tk, grp, "日线", g.set_index("date")[["open", "high", "low", "close", "volume"]], q200)
    T = pd.DataFrame(rows, columns=["grp", "tf", "inst", "method", "ts", "big", "st", "u", "risk"])
    T.to_csv("short_range_trades.csv.gz", index=False); print("trades", len(T))
