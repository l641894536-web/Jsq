"""美股夜盘/盘前盘后要不要算：币安股票永续（24小时交易）上比较几种突破做多规则。

S  现行：只用美股时段小时线（纽约 9:00-15:59）出信号，L=7；止损/跟踪用时段K线算，但24小时都生效
H  混合：价位还是按时段K线算（同S），但任何一根小时线（包括盘前盘后夜盘）收盘站上就进
A  全天：24小时K线，L=24（和币一样）
B  全天快：24小时K线，L=7
都只做多、只在纳指牛市（QQQ 上个收盘在200日线上）、出场F（1R后保本+跟踪3天低点、趋势反转、最多14个自然日）。
数据只有币安股票永续上市以来（2026年2-10月起），样本短，结论只能当参考。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import numpy as np
import pandas as pd

COST, BUF, MIN_RISK, MAX_RISK = 0.001, 0.001, 0.004, 0.08
MAIN = ["AMD", "MU", "DELL"]
SKIP = set("""BTC ETH BNB SOL XRP DOGE ADA PAXG XAU XAG XAUT XPT XPD COPPER NATGAS CL C F O Q MET ALL CFG IR ON
QQQ SPY IWM SMH XLE XBI GDX URNM EWJ EWT EWY EWZ EWZS BITO TBT TMF SOXL SOXS SQQQ TQQQ TZA UVXY TSLL NVDL MSTU MUU KORU
SKUU SKDD RUM""".split())


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def sim(ts, o, h, l, c, LS, STOP0, TRAIL, FLIP, max_days=14):
    out = []; i, n = 1, len(c)
    while i < n - 1:
        if not LS[i]:
            i += 1; continue
        entry, stop = c[i], STOP0[i]; R = entry - stop
        if not (np.isfinite(R) and MIN_RISK * entry <= R <= MAX_RISK * entry):
            i += 1; continue
        armed, mfe, j = False, 0.0, i + 1
        while j < n:
            if l[j] <= stop:
                px = stop if o[j] > stop else o[j]; why = "stop"; break
            mfe = max(mfe, (h[j] - entry) / R)
            if mfe >= 1: armed = True
            if armed and np.isfinite(TRAIL[j]):
                stop = max(stop, max(entry, TRAIL[j]))
            if FLIP[j] or (ts[j] - ts[i]) >= np.timedelta64(max_days, "D") or j == n - 1:
                px = c[j]; why = "flip" if FLIP[j] else "time"; break
            j += 1
        out.append(dict(ts=ts[i], i=i, entry=entry, R_pct=R / entry, r=(px - entry) / R - COST * entry / R, mfe=mfe, why=why))
        i = j + 1
    return out


def pure(g, L):
    """全天K线自己算（A/B）"""
    c = g.close; up = ema(c, 20) > ema(c, 50)
    LS = (up & (c > g.high.rolling(L).max().shift(1)) & (c > c.shift(L))).to_numpy()
    STOP0 = (g.low.rolling(L).min() * (1 - BUF)).to_numpy()
    TRAIL = (g.low.rolling(3 * L).min() * (1 - BUF)).to_numpy()
    FLIP = (~up & up.shift(1, fill_value=False)).to_numpy()
    return LS, STOP0, TRAIL, FLIP


def sess_based(g):
    """价位按时段K线算，映射到24小时K线上。返回 S（只在时段K线收盘进）和 H（任何小时收盘站上就进）"""
    s = g[g.sess].copy()
    c = s.close; up = ema(c, 20) > ema(c, 50)
    s["hi7"] = s.high.rolling(7).max(); s["lo7"] = s.low.rolling(7).min(); s["lo21"] = s.low.rolling(21).min()
    s["up"] = up; s["flip"] = ~up & up.shift(1, fill_value=False)
    s["sig"] = up & (c > s.hi7.shift(1)) & (c > c.shift(7))
    s["c6"] = c.shift(6)                       # 下一根算"7根前"的收盘
    G = g.join(s[["hi7", "lo7", "lo21", "up", "flip", "sig", "c6"]])
    # 非时段K线：用最近一根已经收完的时段K线的值
    last = G[["hi7", "lo7", "lo21", "up", "c6"]].copy()
    last.loc[~G.sess] = np.nan
    last = last.ffill()
    ext = ~G.sess
    lvl = last.hi7; lo_ext = np.minimum(last.lo7, G.low.where(ext).groupby((~ext).cumsum()).cummin())  # 盘外进场：止损取时段7根低点和盘外以来低点的较低者
    sigH = G.sig.fillna(False).astype(bool) | (ext & last.up.fillna(False).astype(bool) & (G.close > lvl) & (G.close > last.c6))
    STOP0 = np.where(G.sess, G.lo7, lo_ext) * (1 - BUF)
    TRAIL = last.lo21.where(ext, G.lo21).ffill() * (1 - BUF)
    FLIP = G.flip.fillna(False).astype(bool).to_numpy()
    LS_S = (G.sess & G.sig.fillna(False).astype(bool)).to_numpy()
    return LS_S, sigH.to_numpy(), np.asarray(STOP0, float), TRAIL.to_numpy(), FLIP


def main():
    q = load.us_daily("QQQ", start="2025-01-01").set_index("date")["adj_close"]
    bull = (q > q.rolling(200).mean()).shift(1)
    bull.index = pd.to_datetime(bull.index)
    raw = load.binance("1h", start="2026-01-01")
    raw["sym"] = raw.symbol.str.replace("USDT", "", regex=False)
    syms = [s for s in raw.sym.unique() if s not in SKIP]
    rows = []
    for sym in syms:
        g = raw[raw.sym == sym].sort_values("ts").reset_index(drop=True)
        if len(g) < 1500: continue
        ny = g.ts.dt.tz_convert("America/New_York")
        g["sess"] = (ny.dt.weekday < 5) & (ny.dt.hour >= 9) & (ny.dt.hour <= 15)
        g["nyd"] = ny.dt.tz_localize(None).dt.normalize()
        ts = g.ts.dt.tz_convert(None).to_numpy(); o, h, l, c = (g[k].to_numpy(float) for k in ["open", "high", "low", "close"])
        LS_S, LS_H, ST, TR, FL = sess_based(g)
        variants = {"S": (LS_S, ST, TR, FL), "H": (LS_H, ST, TR, FL), "A": pure(g, 24), "B": pure(g, 7)}
        for v, (LS, S0, T, F) in variants.items():
            for t in sim(ts, o, h, l, c, LS, S0, T, F):
                t.update(sym=sym, v=v, sess_entry=bool(g.sess.iloc[t["i"]]), bull=bull.reindex([g.nyd.iloc[t["i"]]], method="ffill").iloc[0])
                rows.append(t)
    T = pd.DataFrame(rows)
    T = T[T.bull == True]
    T.to_csv("/home/claude/bt/ext_hours_trades.csv", index=False)
    mid = T.ts.quantile(0.5)

    def summ(x):
        if len(x) == 0: return pd.Series(dtype=float)
        return pd.Series({"笔数": len(x), "胜率": round((x.r > 0).mean() * 100), "平均R": round(x.r.mean(), 3),
                          "总R": round(x.r.sum(), 1), "前半平均R": round(x[x.ts < mid].r.mean(), 3), "后半平均R": round(x[x.ts >= mid].r.mean(), 3),
                          "股票数": x.sym.nunique()})
    print("样本：", T.ts.min(), "→", T.ts.max(), "；股票", T.sym.nunique(), "只")
    print("\n== 全部单只股票永续 ==")
    print(T.groupby("v").apply(summ).to_string())
    print("\n== 只看 AMD/美光/戴尔 ==")
    print(T[T.sym.isin(MAIN)].groupby("v").apply(summ).to_string())
    print("\n== H 规则里：时段内进 vs 盘外进 ==")
    print(T[T.v == "H"].groupby("sess_entry").apply(summ).to_string())
    # 盘外先站上的那些：如果等到时段收盘确认（S），结果怎样
    print("\n== 每只票 S vs H 平均R（看是不是普遍） ==")
    p = T[T.v.isin(["S", "H"])].groupby(["sym", "v"]).r.mean().unstack()
    print("H 比 S 好的股票数:", int((p.H > p.S).sum()), "/", int(p.notna().all(axis=1).sum()))
    p2 = T[T.v.isin(["S", "A"])].groupby(["sym", "v"]).r.mean().unstack()
    print("A 比 S 好的股票数:", int((p2.A > p2.S).sum()), "/", int(p2.notna().all(axis=1).sum()))


if __name__ == "__main__":
    main()
