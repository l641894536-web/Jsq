"""规则冻结后的自动记账（不用真钱）：从 FREEZE 起，按交易台现行规则逐笔记下信号和结果，写成 gh-pages 的 ledger.json。
由 .github/workflows/env-page.yml 在每次数据更新后运行。算法和回测、交易台页面是同一套：
  突破 / 技术面翻多：research/contract_bt.py 的 simulate（出场F：止损=前L根最低×0.999，浮盈1倍后止损=max(开仓价,3L根最低)，小时线EMA反穿或满10天离场）
  回调企稳：research/dip_clean_bt.py（跌够=收盘≤前35根最高×e^(−2σ)；企稳=收盘站上前4根最高且在高点下方；止损=最低×e^(−0.3σ)；1倍保本；回到高点全平；最多70根）
  放量跳空：research/ep_bt.py（开盘比前收高≥8%、量≥50日均量3倍，第二天开盘进，止损=跳空日最低，拿20个交易日）
规则（哪个品种、什么环境、哪个方向才算数）：
  黄金、白银：自身50日线上方，突破做多（2026-11-11 起由200日线改为50日线，用户同意；回测见 research/metals50_stats.py）
  7个主流币：比特币50日线上方 → 突破做多、技术面翻多做多；下方 → 跌破做空
  AMD、美光、戴尔：纳指200日线上方 → 突破做多、技术面翻多做多；下方 → 回调企稳做多（且纳指前一天在跌）
  币安有合约的美股：纳指200日线上方，放量跳空做多
数据：data 分支的币安小时线/日线（最新到昨天UTC），所以账本比实时晚一天左右。金额按100U保证金×5倍（名义500U），已扣手续费。
用法：python pages/ledger.py --data <data分支目录> --jsq <仓库目录> --out ledger.json [--freeze 2026-11-10]"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--jsq", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--freeze", default="2026-11-10")
args = ap.parse_args()
sys.path.insert(0, args.jsq); os.environ["MARKET_DATA"] = args.data
from market_data import load  # noqa: E402

FREEZE = pd.Timestamp(args.freeze, tz="UTC")
COST, BUF, MIN_RISK, MAX_RISK, NOTIONAL = 0.001, 0.001, 0.004, 0.08, 500.0
METALS, CRYPTO, MAIN = ["XAUUSDT", "XAGUSDT"], ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], ["AMDUSDT", "MUUSDT", "DELLUSDT"]
NAME = {"XAUUSDT": "黄金", "XAGUSDT": "白银", "BTCUSDT": "比特币", "ETHUSDT": "以太坊", "SOLUSDT": "SOL", "BNBUSDT": "BNB", "XRPUSDT": "XRP", "DOGEUSDT": "狗狗币",
        "ADAUSDT": "ADA", "AMDUSDT": "AMD", "MUUSDT": "美光", "DELLUSDT": "戴尔"}
ema = lambda s, n: s.ewm(span=n, adjust=False).mean()


def simulate(df, L, LS, SS, bpd, max_days=10):
    """contract_bt.simulate 出场F 的原样移植；最后一根还没离场的单子标 open"""
    df = df.reset_index(drop=True); c_ = df["close"]
    up = ema(c_, 20) > ema(c_, 50)
    CU = (up & ~up.shift(1, fill_value=False)).to_numpy(); CD = (~up & up.shift(1, fill_value=False)).to_numpy()
    o, h, l, c = (df[k].to_numpy(float) for k in ["open", "high", "low", "close"]); ts = df["ts"].to_numpy()
    SL_LO, SL_HI = df["low"].rolling(L).min().to_numpy(), df["high"].rolling(L).max().to_numpy()
    LO3, HI3 = df["low"].rolling(3 * L).min().to_numpy(), df["high"].rolling(3 * L).max().to_numpy()
    LS, SS = np.asarray(LS, bool), np.asarray(SS, bool); max_bars = max_days * bpd; out = []; i, n = 60, len(df)
    while i < n - 1:
        side = 1 if LS[i] else (-1 if SS[i] else 0)
        if side == 0: i += 1; continue
        entry = c[i]; stop0 = SL_LO[i] * (1 - BUF) if side == 1 else SL_HI[i] * (1 + BUF); R = (entry - stop0) * side
        if not (MIN_RISK * entry <= R <= MAX_RISK * entry): i += 1; continue
        stop, armed, mfe, j = stop0, False, 0.0, i + 1
        while j < n:
            adverse, fav = (l[j], h[j]) if side == 1 else (h[j], l[j])
            if (adverse - stop) * side <= 0:
                px = stop if (o[j] - stop) * side > 0 else o[j]; why = "stop"; break
            mfe = max(mfe, (fav - entry) * side / R)
            if mfe >= 1.0: armed = True
            if armed:
                trail = LO3[j] * (1 - BUF) if side == 1 else HI3[j] * (1 + BUF)
                new = max(entry, trail) if side == 1 else min(entry, trail); stop = max(stop, new) if side == 1 else min(stop, new)
            flip = CD[j] if side == 1 else CU[j]
            if flip or (j - i) >= max_bars or j == n - 1:
                px = c[j]; why = "flip" if flip else ("time" if (j - i) >= max_bars else "open"); break
            j += 1
        r = (px - entry) * side / R - COST * entry / R
        out.append(dict(ts=ts[i], exit_ts=ts[j], side=side, entry=entry, stop0=stop0, stop=stop, px=px, R_pct=R / entry, r=r, why=why))
        i = j + 1
    return pd.DataFrame(out)


def brk_signals(df, L):
    c = df["close"]; up = ema(c, 20) > ema(c, 50)
    hi, lo = df["high"].rolling(L).max().shift(1), df["low"].rolling(L).min().shift(1)
    return (up & (c > hi) & (c > c.shift(L))).fillna(False), (~up & (c < lo) & (c < c.shift(L))).fillna(False)


def tech_signals(df, L, dtr):
    """技术面综合分翻多/翻空（research/indicator_bt.py 的"综合分"）"""
    c = df["close"]; ma = ema(c, 20) > ema(c, 50)
    macd = ema(c, 12) - ema(c, 26); hist = macd - ema(macd, 9)
    d = c.diff(); u = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + u / dn.replace(0, np.nan))
    hi, lo = df["high"].rolling(L).max().shift(1), df["low"].rolling(L).min().shift(1)
    sc = np.where(ma, 1, -1) + np.where(hist > 0, 1, -1) + np.where(rsi >= 70, 0, np.where(rsi >= 55, 1, np.where(rsi > 45, 0, np.where(rsi > 30, -1, 0)))) \
        + np.where(c > hi, 1, np.where(c < lo, -1, 0)) + np.nan_to_num(dtr)
    sc = pd.Series(sc, index=c.index)
    return ((sc >= 2) & (sc.shift(1) < 2)).fillna(False), ((sc <= -2) & (sc.shift(1) > -2)).fillna(False)


def day_trend(daily, ts, stock):
    """日线方向（和页面 needD1/dayTrendAt 一样）：币安1d，股票去掉周末；收盘在50日均线上方且均线比5天前高=+1"""
    k = daily.copy()
    if stock: k = k[k.ts.dt.dayofweek < 5]
    k = k.reset_index(drop=True); m = k.close.rolling(50).mean()
    tr = np.where((k.close > m) & (m > m.shift(5)), 1, np.where((k.close < m) & (m < m.shift(5)), -1, 0))
    day0 = ts.dt.floor("D").to_numpy(); idx = np.searchsorted(k.ts.to_numpy(), day0, side="left") - 1
    return np.where(idx >= 0, tr[np.clip(idx, 0, None)], 0).astype(float)


def above_ma(close, n):
    """前一天收盘是否在n日均线上方（index=日期）"""
    close = close.dropna(); return (close > close.rolling(n).mean()).where(close.rolling(n).count() >= n).shift(1)


def session(g):
    ny = g.ts.dt.tz_convert("America/New_York")
    return g[((ny.dt.dayofweek < 5) & (ny.dt.hour >= 9) & (ny.dt.hour <= 15)).to_numpy()].reset_index(drop=True)


def dip_episodes(S, ndx_up, bear):
    """回调企稳（熊市、纳指前一天在跌）。S=交易时段小时线"""
    o, h, l, c = (S[k].to_numpy(float) for k in ["open", "high", "low", "close"]); ts = S.ts
    day = ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    dc = S.groupby(day.to_numpy()).close.last(); sig = np.log(dc).diff().rolling(20).std().shift(1).reindex(day, method="ffill").to_numpy()
    H5 = pd.Series(h).shift(1).rolling(35).max().to_numpy(); H4 = pd.Series(h).shift(1).rolling(4).max().to_numpy()
    out, N, t = [], len(c), 36
    while t < N - 1:
        s = sig[t]
        if not (np.isfinite(s) and np.isfinite(H5[t]) and c[t] <= H5[t] * np.exp(-2 * s)): t += 1; continue
        top, lowest, k = H5[t], l[t], None
        for u in range(t, min(N, t + 35)):
            lowest = min(lowest, l[u])
            if u > t and c[u] > H4[u] and c[u] < top: k = u; break
        if k is None: t += 35; continue
        E0, stop0 = c[k], lowest * np.exp(-0.3 * s); R = E0 - stop0; st = stop0; px = None; why = "open"; j = k
        for j in range(k + 1, min(N, k + 71)):
            if l[j] <= st: px = min(o[j], st); why = "stop"; break
            if h[j] >= E0 + R: st = max(st, E0)
            if h[j] >= top: px = max(o[j], top); why = "target"; break
        if px is None:
            j = min(N - 1, k + 70); px = c[j]; why = "time" if k + 70 <= N - 1 else "open"
        d = day.iloc[k]; ok = bool(bear.reindex([d], method="ffill").iloc[0] == 1) and bool(ndx_up.reindex([d], method="ffill").iloc[0] == 0)
        days = (ts.iloc[j] - ts.iloc[k]).total_seconds() / 86400
        out.append(dict(ts=ts.iloc[k], exit_ts=ts.iloc[j], entry=E0, stop0=stop0, stop=st, px=px, why=why, ok=ok, target=top,
                        u=((px / E0 - 1) - 0.001 - 0.0003 * days) * NOTIONAL))
        t = max(t + 1, j + 1)
    return out


def main():
    syms = METALS + CRYPTO + MAIN
    H = load.binance("1h", syms, start=str((FREEZE - pd.Timedelta(days=150)).date())).sort_values(["symbol", "ts"])
    D = load.binance("1d", syms, start="2024-06-01"); D["ts"] = pd.to_datetime(D["ts"] if "ts" in D else D["date"], utc=True); D = D.sort_values(["symbol", "ts"])
    us = load.us_daily(["QQQ", "^NDX"]); us["date"] = pd.to_datetime(us.date); px = us.pivot(index="date", columns="ticker", values="close")
    qqq_bull = above_ma(px["QQQ"], 200); ndx = px["^NDX"].dropna(); ndx_up = (ndx > ndx.shift(1)).astype(float).shift(1)
    dclose = {s: g.set_index(g.ts.dt.tz_localize(None).dt.normalize()).close for s, g in D.groupby("symbol")}
    btc_bull = above_ma(dclose["BTCUSDT"], 50)
    trades = []

    def add(sym, rule, t, bull_flag, want_bull, tz="UTC"):
        if t.empty: return
        for _, x in t.iterrows():
            ts = pd.Timestamp(x.ts).tz_localize("UTC") if pd.Timestamp(x.ts).tzinfo is None else pd.Timestamp(x.ts)
            if ts < FREEZE: continue
            d = ts.tz_convert(tz).tz_localize(None).normalize(); b = bull_flag.reindex([d], method="ffill").iloc[0]
            if pd.isna(b) or bool(b) != want_bull: continue
            trades.append(dict(sym=sym, name=NAME[sym], rule=rule, dir="多" if x.side == 1 else "空", t_in=ts.isoformat(), px_in=round(float(x.entry), 6), stop=round(float(x.stop0), 6),
                               t_out=None if x.why == "open" else pd.Timestamp(x.exit_ts).isoformat(), px_out=round(float(x.px), 6), status="持仓中" if x.why == "open" else "已平",
                               why={"stop": "止损", "flip": "小时线趋势反转", "time": "满10天", "open": ""}[x.why], u=round(float(x.r * x.R_pct * NOTIONAL), 1)))

    for sym, g in H.groupby("symbol"):
        g = g.reset_index(drop=True); stock = sym in MAIN
        R = session(g) if stock else g; L = 7 if stock else 24
        if len(R) < 120: continue
        zero = pd.Series(False, index=R.index)
        bl, bs = brk_signals(R, L); tl, _ = tech_signals(R, L, day_trend(D[D.symbol == sym], R.ts, stock))
        if sym in METALS:
            if dclose[sym].count() >= 51: add(sym, "突破", simulate(R, L, bl, zero, L), above_ma(dclose[sym], 50), True, "America/New_York")
        elif sym in CRYPTO:
            add(sym, "突破", simulate(R, L, bl, zero, L), btc_bull, True); add(sym, "技术面翻多", simulate(R, L, tl, zero, L), btc_bull, True)
            add(sym, "跌破", simulate(R, L, zero, bs, L), btc_bull, False)
        else:
            add(sym, "突破", simulate(R, L, bl, zero, L), qqq_bull, True, "America/New_York"); add(sym, "技术面翻多", simulate(R, L, tl, zero, L), qqq_bull, True, "America/New_York")
            for e in dip_episodes(R, ndx_up, (qqq_bull == 0).astype(float).where(qqq_bull.notna())):
                if e["ts"] < FREEZE or not e["ok"]: continue
                trades.append(dict(sym=sym, name=NAME[sym], rule="回调企稳", dir="多", t_in=e["ts"].isoformat(), px_in=round(e["entry"], 4), stop=round(e["stop"], 4),
                                   t_out=None if e["why"] == "open" else e["exit_ts"].isoformat(), px_out=round(e["px"], 4), status="持仓中" if e["why"] == "open" else "已平",
                                   why={"stop": "止损/保本", "target": "到目标", "time": "满10天", "open": ""}[e["why"]], u=round(e["u"], 1)))
    # 放量跳空（币安有合约的美股，纳指牛市）
    try:
        st = json.load(open(f"{args.data}/status.json"))
        etf = {"SOXL", "TQQQ", "SQQQ", "QQQ", "SPY", "IWM", "SMH", "GDX", "XLE", "DIA"}
        perps = sorted({p[:-4] for p in st["stages"]["binance"].get("stock_perps", [])} - etf)
        u = load.us_daily(perps); u["date"] = pd.to_datetime(u.date)
        for tk, g in u.groupby("ticker"):
            g = g.sort_values("date").reset_index(drop=True)
            if len(g) < 60: continue
            v50 = g.volume.rolling(50).mean().shift(1); pc = g.close.shift(1)
            for i in np.flatnonzero(((g.open / pc - 1 >= 0.08) & (g.volume >= 3 * v50) & (pc > 3) & (g.date >= FREEZE.tz_localize(None))).to_numpy()):
                b = qqq_bull.reindex([g.date[i]], method="ffill").iloc[0]
                if i + 1 >= len(g) or pd.isna(b) or not bool(b): continue
                E0, stop = g.open[i + 1], g.low[i]
                if not (E0 - stop > 0.002 * E0): continue
                last = min(len(g) - 1, i + 21); px = None; why = "open" if last < i + 21 else "time"; j = last
                for j in range(i + 1, last + 1):
                    if g.low[j] <= stop: px = min(g.open[j], stop) if j > i + 1 else stop; why = "stop"; break
                if px is None: j = last; px = g.close[j]
                days = (g.date[j] - g.date[i + 1]).days
                trades.append(dict(sym=tk + "USDT", name=tk, rule="放量跳空", dir="多", t_in=g.date[i + 1].isoformat(), px_in=round(float(E0), 2), stop=round(float(stop), 2),
                                   t_out=None if why == "open" else g.date[j].isoformat(), px_out=round(float(px), 2), status="持仓中" if why == "open" else "已平",
                                   why={"stop": "止损", "time": "满20天", "open": ""}[why], u=round(float(((px / E0 - 1) - COST - 0.0003 * days) * NOTIONAL), 1)))
    except Exception as e:
        print("ep skipped:", repr(e))
    trades.sort(key=lambda x: x["t_in"], reverse=True)
    T = pd.DataFrame(trades); closed = T[T.status == "已平"] if len(T) else T
    by = [] if not len(T) else [dict(rule=k, n=int(len(x)), closed=int((x.status == "已平").sum()), u=round(float(x.u.sum()), 1), win=int((x.u > 0).sum())) for k, x in T.groupby("rule")]
    out = dict(frozen=args.freeze, data_to=str(H.ts.max()), n=int(len(T)), closed=int(len(closed)), open=int(len(T) - len(closed)),
               total_u=round(float(T.u.sum()), 1) if len(T) else 0.0, closed_u=round(float(closed.u.sum()), 1) if len(closed) else 0.0,
               win=int((closed.u > 0).sum()) if len(closed) else 0, by_rule=by, trades=trades[:300])
    json.dump(out, open(args.out, "w"), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"ledger: {out['n']} trades since {args.freeze} ({out['closed']} closed, {out['closed_u']:+.1f}U), data to {out['data_to']}")
    return out, T


if __name__ == "__main__":
    main()
