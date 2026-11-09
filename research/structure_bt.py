"""K线结构（摆动高低点 / 突破结构）到底有没有用？和页面 swingStructure() 同一套定义：
  平均波幅 ATR = TR 的 1/14 指数平均；价格从极值反向走出 2 倍 ATR 就确认一个摆动高点/低点；
  收盘高于最近确认的高点 → 上涨结构；收盘低于最近确认的低点 → 下跌结构。
每次结构转向（翻多/翻空）记一个事件，看三件事：
  1) 方向：之后24小时涨/跌的比例，对比任意时刻的比例（页面原来只看这个）
  2) 幅度：之后24小时走了几倍 ATR（按结构方向记正负），对比任意时刻
  3) 按结构做：转向收盘进场，最近确认的反向摆动点是认错位（1R），结构反转时收盘离场（最多拿10天），
     扣来回0.1%和多单资金费0.03%/天；对照组 = 结构已经是这个方向、随便某根K线进场，同样的认错和离场
样本 2021-11 → 2026-10，2024-05 前后分两段。"""
import sys, os, json
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
from market_data.config import DK_STOCKS_1H_OTHER
import pandas as pd, numpy as np

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
COST, FUND_DAY = 0.001, 0.0003


def structure(h, l, c, theta=2.0):
    n = len(c)
    atr = np.empty(n); p = None
    for i in range(n):
        pc = c[i - 1] if i else c[i]
        tr = max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc))
        p = tr if p is None else p + (tr - p) / 14
        atr[i] = p
    trend = np.zeros(n, np.int8); lastH = np.full(n, np.nan); lastL = np.full(n, np.nan)
    d = 0; ext = ei = None; hi = lo = None; hiI = loI = 0
    LH = LL = np.nan; tr_ = 0
    for t in range(n):
        if d == 0:
            if hi is None:
                hi, hiI, lo, loI = h[t], t, l[t], t
            if h[t] > hi: hi, hiI = h[t], t
            if l[t] < lo: lo, loI = l[t], t
            if hi - lo >= theta * atr[t]:
                if hiI > loI: d, ext = 1, hi; LL = lo
                else: d, ext = -1, lo; LH = hi
        elif d == 1:
            if h[t] >= ext: ext = h[t]
            elif l[t] <= ext - theta * atr[t]: LH = ext; d, ext = -1, l[t]
        else:
            if l[t] <= ext: ext = l[t]
            elif h[t] >= ext + theta * atr[t]: LL = ext; d, ext = 1, h[t]
        if not np.isnan(LH) and c[t] > LH and tr_ != 1: tr_ = 1
        elif not np.isnan(LL) and c[t] < LL and tr_ != -1: tr_ = -1
        trend[t], lastH[t], lastL[t] = tr_, LH, LL
    return trend, lastH, lastL, atr


def trade(c, trend, t, s, inval, maxbars, hours_per_bar):
    R = s * (c[t] - inval)
    if not (R > 0):
        return None
    n = len(c)
    for u in range(t + 1, min(n, t + 1 + maxbars)):
        if trend[u] == -s:
            break
    else:
        u = min(n, t + 1 + maxbars) - 1
    if u <= t:
        return None
    days = (u - t) * hours_per_bar / 24
    cost = (COST + (FUND_DAY * days if s == 1 else 0)) * c[t] / R
    return s * (c[u] - c[t]) / R - cost, R / c[t]


def study(df, tf, h24, maxbars, hours_per_bar, env, ctrl_stride=7):
    """df: ts, open, high, low, close（一个品种一个周期）。env: 日期→1/0 牛熊。"""
    df = df.sort_values("ts").reset_index(drop=True)
    h, l, c = (df[k].to_numpy(float) for k in ["high", "low", "close"])
    ts = df.ts
    trend, LH, LL, atr = structure(h, l, c)
    day = ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    bull = env.reindex(day, method="ffill").to_numpy()
    ok = ((ts >= START) & (ts < END)).to_numpy()
    n = len(c)
    rows = []
    prev = np.r_[0, trend[:-1]]
    for t in np.where(ok)[0]:
        if t + h24 >= n or not np.isfinite(bull[t]):
            continue
        flip = trend[t] != 0 and trend[t] != prev[t]
        ctrl = (not flip) and trend[t] != 0 and t % ctrl_stride == 0
        if not (flip or ctrl):
            continue
        s = int(trend[t])
        inval = LL[t] if s == 1 else LH[t]
        if not (s * (c[t] - inval) >= 0.5 * atr[t]):     # 认错位离现价不到半个ATR：止损太窄，不算
            continue
        tr = trade(c, trend, t, s, inval, maxbars, hours_per_bar)
        if tr is None:
            continue
        f24 = c[t + h24] - c[t]
        rows.append((ts.iloc[t], "flip" if flip else "ctrl", s, int(bull[t]), np.sign(f24) * s > 0, s * f24 / atr[t], tr[0], tr[1]))
    # 任意时刻基准（每7根取一根）
    base = [(c[t + h24] - c[t]) / atr[t] for t in np.where(ok)[0][::7] if t + h24 < n]
    base_up = np.mean([b > 0 for b in base]) if base else np.nan
    out = pd.DataFrame(rows, columns=["ts", "kind", "side", "bull", "right24", "move24", "r", "R_pct"])
    out["tf"] = tf
    return out, dict(base_up=base_up, base_move=float(np.mean(base)) if base else np.nan, trend=pd.DataFrame({"ts": ts.to_numpy(), "trend": trend}))


def daily_bull(df):
    d = df.assign(day=df.ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize())
    d = d[d.day.dt.dayofweek < 5].groupby("day").close.last()
    return (d > d.rolling(200).mean()).astype(float).where(d.rolling(200).count() >= 200).shift(1)


def resample(df, rule):
    g = df.set_index("ts").resample(rule, label="left", closed="left")
    o = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    return o


def index_bull(tk):
    d = load.us_daily(tk).set_index("date").close
    return (d > d.rolling(200).mean()).astype(float).where(d.rolling(200).count() >= 200).shift(1)


def run():
    allr, bases, trends = [], [], {}

    def add(group, sym, df, tf, h24, maxbars, hpb, env):
        r, b = study(df, tf, h24, maxbars, hpb, env)
        allr.append(r.assign(group=group, sym=sym))
        trends[(sym, tf)] = b["trend"]
        bases.append(dict(group=group, sym=sym, tf=tf, base_up=b["base_up"], base_move=b["base_move"]))

    # 金银：1h、4h、15m（Dukascopy 5m 合成）
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2020-01")
    dk5 = load.dukascopy(["XAUUSD", "XAGUSD"], interval="5m", start="2021-01")
    for sym, grp in [("XAUUSD", "gold"), ("XAGUSD", "silver")]:
        g = dk[dk.symbol == sym][["ts", "open", "high", "low", "close"]]
        env = daily_bull(g)
        add(grp, sym, g, "1h", 24, 240, 1, env)
        add(grp, sym, resample(g, "4h"), "4h", 6, 60, 4, env)
        g5 = dk5[dk5.symbol == sym][["ts", "open", "high", "low", "close"]]
        add(grp, sym, resample(g5, "15min"), "15m", 96, 960, 0.25, env)
    # 加密：1h、4h（2020起），15m（2022起）
    cr = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]
    b1 = load.binance("1h", cr)
    btc = b1[b1.symbol == "BTCUSDT"].copy(); btc["day"] = btc.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    bd = btc.groupby("day").close.last()
    cenv = (bd > bd.rolling(200).mean()).astype(float).where(bd.rolling(200).count() >= 200).shift(1)
    b15 = load.binance("15m", cr)
    for sym in cr:
        g = b1[b1.symbol == sym][["ts", "open", "high", "low", "close"]]
        add("crypto", sym, g, "1h", 24, 240, 1, cenv)
        add("crypto", sym, resample(g, "4h"), "4h", 6, 60, 4, cenv)
        g15 = b15[b15.symbol == sym][["ts", "open", "high", "low", "close"]]
        if len(g15) > 50000:
            add("crypto", sym, g15, "15m", 96, 960, 0.25, cenv)
    # 美股：交易时段小时线（1天≈7根），4h 按时段合成（1天≈2根）
    ndx, spx = index_bull("QQQ"), index_bull("^GSPC")
    main3 = ["AMD", "MU", "DELL"]
    tech = ["AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX", "MRVL",
            "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN"]
    st = load.dukascopy([s + "USUSD" for s in main3 + tech + DK_STOCKS_1H_OTHER], start="2020-06")
    for sym, g in st.groupby("symbol"):
        tk = sym.replace("USUSD", "")
        grp = "stock_main" if tk in main3 else ("stock_other" if tk in tech else "stock_nontech")
        g = g[["ts", "open", "high", "low", "close"]].sort_values("ts")
        env = spx if grp == "stock_nontech" else ndx
        add(grp, tk, g, "1h", 7, 70, 24 / 7, env)
        g4 = resample(g, "4h")
        add(grp, tk, g4, "4h", 2, 20, 12, env)
    # 其他大宗
    cm = load.dukascopy(["XPTCMDUSD", "XPDCMDUSD", "COPPERCMDUSD", "GASCMDUSD"], start="2020-01")
    for sym, g in cm.groupby("symbol"):
        g = g[["ts", "open", "high", "low", "close"]].sort_values("ts")
        env = daily_bull(g)
        add("commod", sym, g, "1h", 23, 230, 1, env)
        add("commod", sym, resample(g, "4h"), "4h", 6, 60, 4, env)
    # 大周期当时的结构（只用已经收完的大周期K线）
    DUR = {"15m": pd.Timedelta("15min"), "1h": pd.Timedelta("1h"), "4h": pd.Timedelta("4h")}
    for k, x in enumerate(allr):
        if x.empty:
            continue
        sym, tf = x.sym.iloc[0], x.tf.iloc[0]
        x = x.assign(close_ts=x.ts + DUR[tf]).sort_values("close_ts")
        for H in ["1h", "4h"]:
            if DUR[H] <= DUR[tf] or (sym, H) not in trends:
                continue
            tr = trends[(sym, H)].copy()
            tr["close_ts"] = pd.to_datetime(tr.ts) + DUR[H]
            x = pd.merge_asof(x, tr[["close_ts", "trend"]].rename(columns={"trend": "t" + H}).sort_values("close_ts"), on="close_ts", direction="backward")
        allr[k] = x
    r = pd.concat(allr, ignore_index=True)
    r["half"] = np.where(r.ts < MID, "h1", "h2")
    r["env"] = np.where(r.bull == 1, "bull", "bear")
    r["dir"] = np.where(r.side == 1, "long", "short")
    r.to_csv("structure_events.csv", index=False)
    pd.DataFrame(bases).to_csv("structure_base.csv", index=False)
    return r, pd.DataFrame(bases)


if __name__ == "__main__":
    r, b = run()
    print(len(r), r.groupby(["group", "tf", "kind"]).size().unstack().to_string())
