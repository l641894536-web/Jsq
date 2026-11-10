"""把结论卡上的技术指标一个个拆开检验（小时线，2021-11 → 2026-10，牛熊分开，前后两段）。
指标（和交易台卡片同一套定义）：
  均线  EMA20 在 EMA50 上=多 / 下=空
  MACD  柱子(12,26,9) >0=多 / <0=空
  RSI   14小时：≥55 偏强、≤45 偏弱；<30 超卖、>70 超买
  位置  收盘突破前24小时最高=多 / 跌破最低=空
  日线  收盘在50日均线上方且均线向上=多 / 下方且向下=空
A 状态检验：指标"看多"和"看空"的时候，之后24小时的涨跌（按100U开5倍折成U，不扣费）——看指标有没有预测力
B 当信号做单：指标翻多就做多、翻空就做空，止损放24小时低/高点，1倍保本+跟踪3天低点（和突破规则同一套出场），扣手续费
品种：黄金、白银（Dukascopy 现货），7个主流币（币安），AMD/美光/戴尔（Dukascopy 交易时段线，每天7根）
牛熊：金银=自身200日线，美股=纳指200日线，币=比特币50日线
用法：python3 indicator_bt.py"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import contract_bt as CB, exit_bt as X

ORIG = CB.signals


def indicators(df, L):
    c = df["close"]
    e20, e50 = CB.ema(c, 20), CB.ema(c, 50)
    macd = CB.ema(c, 12) - CB.ema(c, 26); hist = macd - CB.ema(macd, 9)
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    hi = df["high"].rolling(L).max().shift(1); lo = df["low"].rolling(L).min().shift(1)
    return dict(ma=e20 > e50, hist=hist, rsi=rsi, brk_up=c > hi, brk_dn=c < lo)


def daily_trend(df, tz, bpd):
    """日线：收盘在50日均线上方且均线向上 → 1；下方且向下 → -1；其余0。用前一天的收盘（不偷看）"""
    day = df.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    dc = df.groupby(day).close.last(); m = dc.rolling(50).mean()
    s = pd.Series(np.where((dc > m) & (m > m.shift(5)), 1, np.where((dc < m) & (m < m.shift(5)), -1, 0)), index=dc.index).shift(1)
    return s.reindex(day, method="ffill").to_numpy()


def make_signals(name, I, dtr):
    f = lambda s: s.fillna(False).astype(bool)
    ma, hist, rsi = I["ma"], I["hist"], I["rsi"]
    if name == "均线金叉/死叉":
        L_, S_ = ma & ~ma.shift(1, fill_value=False), ~ma & ma.shift(1, fill_value=True)
    elif name == "MACD金叉/死叉":
        L_, S_ = (hist > 0) & (hist.shift(1) <= 0), (hist < 0) & (hist.shift(1) >= 0)
    elif name == "RSI超卖反弹/超买回落":
        L_, S_ = (rsi > 30) & (rsi.shift(1) <= 30), (rsi < 70) & (rsi.shift(1) >= 70)
    elif name == "RSI转强/转弱(过55/破45)":
        L_, S_ = (rsi >= 55) & (rsi.shift(1) < 55), (rsi <= 45) & (rsi.shift(1) > 45)
    elif name == "突破24小时高/低点":
        L_, S_ = I["brk_up"] & ~I["brk_up"].shift(1, fill_value=False), I["brk_dn"] & ~I["brk_dn"].shift(1, fill_value=False)
    elif name == "综合分翻多/翻空(≥2项净多)":
        sc = np.where(ma, 1, -1) + np.where(hist > 0, 1, -1) + np.where(rsi >= 70, 0, np.where(rsi >= 55, 1, np.where(rsi > 45, 0, np.where(rsi > 30, -1, 0)))) \
            + np.where(I["brk_up"], 1, np.where(I["brk_dn"], -1, 0)) + np.nan_to_num(dtr)
        sc = pd.Series(sc, index=ma.index)
        L_, S_ = (sc >= 2) & (sc.shift(1) < 2), (sc <= -2) & (sc.shift(1) > -2)
    return f(L_), f(S_)


NAMES = ["均线金叉/死叉", "MACD金叉/死叉", "RSI超卖反弹/超买回落", "RSI转强/转弱(过55/破45)", "突破24小时高/低点", "综合分翻多/翻空(≥2项净多)"]


def trades_for(df, L, bpd, tz, bull, grp, sym):
    I = indicators(df, L); dtr = daily_trend(df, tz, bpd); out = []
    for name in NAMES:
        LS, SS = make_signals(name, I, dtr)
        for side in (1, -1):
            def sig(d_, L_, e, _LS=LS, _SS=SS, _s=side):
                a = ORIG(d_, L_, "breakout")
                return (_LS if _s == 1 else _LS & False, _SS if _s == -1 else _SS & False) + a[2:]
            CB.signals = sig
            t = CB.simulate(df, L, "F", entry="breakout", max_hold_days=10, bars_per_day=bpd); CB.signals = ORIG
            if len(t): out.append(X.tagged(t, bull, tz).assign(grp=grp, sym=sym, sig=name))
    # 现在用的突破规则（突破+均线同向+24小时没在跌）做参照
    t = CB.simulate(df, L, "F", entry="breakout", max_hold_days=10, bars_per_day=bpd)
    out.append(X.tagged(t, bull, tz).assign(grp=grp, sym=sym, sig="参照：现在的突破规则"))
    # A 状态检验
    c = df.close; fwd = c.shift(-L) / c - 1
    day = df.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    b = bull.reindex(day, method="ffill").to_numpy()
    S = pd.DataFrame({"ts": df.ts, "fwd": fwd, "env": np.where(pd.isna(b), None, np.where(b == 1, "bull", "bear")),
                      "均线": np.where(I["ma"], 1, -1), "MACD": np.where(I["hist"] > 0, 1, -1),
                      "RSI强弱": np.where(I["rsi"] >= 55, 1, np.where(I["rsi"] <= 45, -1, 0)),
                      "RSI超买超卖": np.where(I["rsi"] < 30, 1, np.where(I["rsi"] > 70, -1, 0)),       # 超卖=看反弹(多)，超买=看回落(空)
                      "位置": np.where(I["brk_up"], 1, np.where(I["brk_dn"], -1, 0)), "日线": dtr})
    S = S[(S.ts >= X.START) & (S.ts < X.END) & S.env.notna() & S.fwd.notna()].assign(grp=grp, sym=sym, half=lambda x: np.where(x.ts < X.MID, "h1", "h2"))
    return pd.concat(out, ignore_index=True), S


def bull50(close):
    close = close.dropna(); return (close > close.rolling(50).mean()).astype(float).where(close.rolling(50).count() >= 50).shift(1)


if __name__ == "__main__":
    T, S = [], []
    us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        g = dk[dk.symbol == sym].sort_values("ts").reset_index(drop=True)
        t, s = trades_for(g, 24, 24, "America/New_York", X.bull_daily(px[fut]), grp, sym); T.append(t); S.append(s)
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = bull50(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        t, s = trades_for(g.sort_values("ts").reset_index(drop=True), 24, 24, "UTC", btc, "主流币", sym); T.append(t); S.append(s)
    st = load.dukascopy([x + "USUSD" for x in ["AMD", "MU", "DELL"]], start="2021-06"); qqq = X.bull_daily(px["QQQ"])
    for sym, g in st.groupby("symbol"):
        t, s = trades_for(g.sort_values("ts").reset_index(drop=True), 7, 7, "America/New_York", qqq, "AMD/美光/戴尔", sym.replace("USUSD", "")); T.append(t); S.append(s)
    T = pd.concat(T, ignore_index=True); S = pd.concat(S, ignore_index=True)
    T["u"] = T.r * T.R_pct * 500
    T.to_csv("indicator_trades.csv.gz", index=False); S.to_pickle("indicator_states.pkl")
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
    print("===== A 状态检验：指标看多/看空时，之后24小时（美股=1个交易日）平均涨跌，按100U开5倍折成U（不扣费；来回手续费约0.5U）")
    rows = []
    for (grp, env), x in S.groupby(["grp", "env"]):
        base = x.fwd.mean() * 500
        for k in ["均线", "MACD", "RSI强弱", "RSI超买超卖", "位置", "日线"]:
            up, dn = x[x[k] == 1], x[x[k] == -1]
            rows.append(dict(品种=grp, 环境="牛" if env == "bull" else "熊", 指标=k, 平时=round(base, 2), 看多时=round(up.fwd.mean() * 500, 2), 看空时=round(dn.fwd.mean() * 500, 2),
                             差=round((up.fwd.mean() - dn.fwd.mean()) * 500, 2), 前段差=round((up[up.half == "h1"].fwd.mean() - dn[dn.half == "h1"].fwd.mean()) * 500, 2),
                             后段差=round((up[up.half == "h2"].fwd.mean() - dn[dn.half == "h2"].fwd.mean()) * 500, 2), 看多占比=f"{len(up)/len(x)*100:.0f}%", 看空占比=f"{len(dn)/len(x)*100:.0f}%"))
    A = pd.DataFrame(rows); print(A.to_string(index=False)); A.to_csv("indicator_state_report.csv", index=False)
    print("\n===== B 当信号做单（止损24小时低/高点，1倍保本+跟踪3天低点，已扣费）：每次平均赚亏U（100U开5倍）")
    rows = []
    for (grp, sig, env, d), x in T.groupby(["grp", "sig", "env", "dir"]):
        if len(x) < 30: continue
        nsym = x.sym.nunique(); months = 60
        rows.append(dict(品种=grp, 信号=sig, 环境="牛" if env == "bull" else "熊", 方向="多" if d == "long" else "空", 笔数=len(x), 每月每品种=round(len(x) / nsym / months, 1), 赚的比例=f"{(x.r > 0).mean()*100:.0f}%",
                         每次U=round(x.u.mean(), 1), 前段U=round(x[x.half == "h1"].u.mean(), 1), 后段U=round(x[x.half == "h2"].u.mean(), 1), 平均R=round(x.r.mean(), 2)))
    B = pd.DataFrame(rows); print(B.to_string(index=False)); B.to_csv("indicator_trade_report.csv", index=False)
