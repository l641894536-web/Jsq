"""A股日线面板（T×N 矩阵），从 market-data 的 csv.xz 读，缓存成 npz。口径同 pages/env_pipeline.py（只要 sh.6 / sz.0 / sz.3）。
另算每日情绪指标和情绪温度（与 env_pipeline 完全一致）。"""
import glob, os
import numpy as np, pandas as pd

DATA = os.environ.get("MARKET_DATA", "/home/claude/market-data")
CACHE = "/home/claude/bt/_apanel.npz"
COLS = ["open", "high", "low", "close", "preclose", "amount", "turn", "pctChg", "tradestatus", "isST"]


def build(start_year=2015):
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        return {k: z[k] for k in z.files}
    parts = []
    for f in sorted(glob.glob(f"{DATA}/a_share/daily/*/*.csv.xz")):
        if int(f.split("/")[-2]) < start_year:
            continue
        d = pd.read_csv(f, usecols=["date", "code"] + COLS, dtype={"date": str, "code": str})
        d = d[d.code.str.match(r"^(sh\.6|sz\.0|sz\.3)")]
        for c in COLS:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    dates = np.sort(df.date.unique()); codes = np.sort(df.code.unique())
    di = pd.Index(dates).get_indexer(df.date); ci = pd.Index(codes).get_indexer(df.code)
    out = {"dates": dates, "codes": codes}
    for c in COLS:
        m = np.full((len(dates), len(codes)), np.nan, dtype="float32")
        m[di, ci] = df[c].to_numpy()
        out[c] = m
    np.savez(CACHE, **out)
    return out


def derive(P):
    """常用派生量：可交易、涨跌停价、涨停/触板/连板、复权价、每日情绪指标和温度。"""
    dates = pd.to_datetime(P["dates"]); codes = P["codes"].astype(str)
    st = np.nan_to_num(P["isST"]).astype(bool)
    traded = (np.nan_to_num(P["tradestatus"]) == 1) & np.isfinite(P["close"]) & (np.nan_to_num(P["amount"]) > 0)
    age = np.cumsum(traded, axis=0)
    ok = traded & (age >= 20) & ~st
    pct = np.where(traded, P["pctChg"], np.nan).astype("float64")
    close = P["close"].astype("float64"); pc = P["preclose"].astype("float64")
    kc = np.char.startswith(codes, "sh.68"); cy = np.char.startswith(codes, "sz.30")
    reform = (dates >= pd.Timestamp("2020-08-24"))[:, None]
    lim = np.where(st, 0.05, 0.10)
    lim = np.where(kc[None, :] | (cy[None, :] & reform), 0.20, lim)
    up = np.floor(pc * (1 + lim) * 100 + 0.5) / 100
    dn = np.floor(pc * (1 - lim) * 100 + 0.5) / 100
    zt = ok & (np.abs(close - up) < 0.0051)
    dtm = ok & (np.abs(close - dn) < 0.0051)
    touched = ok & (P["high"].astype("float64") >= up - 0.0051)
    streak = np.zeros(zt.shape, dtype=np.int16); streak[0] = zt[0]
    for t in range(1, len(zt)):
        streak[t] = (streak[t - 1] + 1) * zt[t]
    ret = np.where(traded, P["pctChg"] / 100.0, 0.0)
    adj = np.where(traded, np.cumprod(1 + ret, axis=0), np.nan)
    A = pd.DataFrame(adj)
    hi250 = A.rolling(250, min_periods=200).max().to_numpy(); lo250 = A.rolling(250, min_periods=200).min().to_numpy()
    ma20 = A.rolling(20, min_periods=15).mean().to_numpy(); ma60 = A.rolling(60, min_periods=45).mean().to_numpy()
    okh = ok & (age >= 250); n_ok = ok.sum(1)
    prev_zt = np.vstack([np.zeros((1, zt.shape[1]), bool), zt[:-1]]); pz = prev_zt & ok
    prem = np.where(pz.sum(1) > 0, np.nansum(np.where(pz, pct, 0), 1) / np.maximum(pz.sum(1), 1), np.nan)
    with np.errstate(all="ignore"):
        ew = np.nanmean(np.where(ok, pct, np.nan), 1) / 100
    amt = np.nansum(np.where(traded, P["amount"], 0), 1) / 1e8
    s = pd.DataFrame({
        "n": n_ok, "涨停": zt.sum(1), "跌停": dtm.sum(1),
        "炸板率": 1 - zt.sum(1) / np.maximum(touched.sum(1), 1),
        "连板高度": np.where(ok, streak, 0).max(1), "昨日涨停今日涨幅": prem,
        "上涨占比": (ok & (pct > 0)).sum(1) / np.maximum(n_ok, 1), "成交额亿": amt,
        "新高减新低占比": ((okh & (adj >= hi250 - 1e-12)).sum(1) - (okh & (adj <= lo250 + 1e-12)).sum(1)) / np.maximum(okh.sum(1), 1),
        "站上20日线占比": (ok & (adj > ma20)).sum(1) / np.maximum(n_ok, 1),
        "站上60日线占比": (ok & (adj > ma60)).sum(1) / np.maximum(n_ok, 1), "等权日收益": ew,
    }, index=dates)
    s["成交额热度"] = s["成交额亿"].rolling(20).mean() / s["成交额亿"].rolling(250).mean()
    s["等权指数"] = (1 + s["等权日收益"].fillna(0)).cumprod()
    s["涨停占比"] = s["涨停"] / s["n"]; s["跌停占比"] = s["跌停"] / s["n"]; s["涨跌停差占比"] = (s["涨停"] - s["跌停"]) / s["n"]
    IND = {"涨停占比": 5, "跌停占比": 5, "涨跌停差占比": 5, "炸板率": 5, "连板高度": 5, "昨日涨停今日涨幅": 5,
           "上涨占比": 5, "成交额热度": 1, "新高减新低占比": 5, "站上20日线占比": 1, "站上60日线占比": 1}
    pr = lambda x: x.rolling(250, min_periods=200).apply(lambda a: (a[-1] > a[:-1]).mean() + 0.5 * (a[-1] == a[:-1]).mean(), raw=True)
    for k, sm in IND.items():
        v = s[k].rolling(sm).mean() if sm > 1 else s[k]
        s[k + "_分位"] = pr(v)
    HOT = ["涨停占比", "涨跌停差占比", "连板高度", "昨日涨停今日涨幅", "上涨占比", "新高减新低占比", "站上20日线占比", "站上60日线占比", "成交额热度"]
    COLD = ["跌停占比", "炸板率"]
    s["温度"] = (s[[h + "_分位" for h in HOT]].sum(axis=1) + (1 - s[[c + "_分位" for c in COLD]]).sum(axis=1)) / 11 * 100
    s["ma200"] = s["等权指数"].rolling(200).mean()
    s["牛"] = (s["等权指数"] > s["ma200"]).shift(1)
    return dict(dates=dates, codes=codes, st=st, traded=traded, ok=ok, age=age, pct=pct, close=close, pc=pc, up=up, dn=dn,
                zt=zt, dtm=dtm, touched=touched, streak=streak, adj=adj, s=s, lim=lim)
