"""A股每日情绪指标（全市场，剔除ST和上市不满20天的新股）。"""
import numpy as np
import pandas as pd

P = "/home/claude/bt/panel"


def load_panel():
    g = {k: np.load(f"{P}/{k}.npy") for k in ["high", "low", "close", "preclose", "amount", "pctChg", "tradestatus", "isST", "turn"]}
    g["dates"] = pd.to_datetime(np.load(f"{P}/dates.npy"))
    g["codes"] = np.load(f"{P}/codes.npy")
    return g


def limits(g):
    dates, codes = g["dates"], g["codes"]
    kc = np.char.startswith(codes.astype(str), "sh.68")
    cy = np.char.startswith(codes.astype(str), "sz.30")
    reform = (dates >= pd.Timestamp("2020-08-24"))[:, None]
    st = g["isST"] == 1
    lim = np.where(st, 0.05, 0.10)
    lim = np.where(kc[None, :] | (cy[None, :] & reform), 0.20, lim)
    pc = g["preclose"].astype("float64")
    up = np.floor(pc * (1 + lim) * 100 + 0.5) / 100
    dn = np.floor(pc * (1 - lim) * 100 + 0.5) / 100
    return up, dn


def compute():
    g = load_panel()
    traded = (g["tradestatus"] == 1) & np.isfinite(g["close"]) & (g["amount"] > 0)
    age = np.cumsum(traded, axis=0)
    ok = traded & (age >= 20) & (g["isST"] == 0)
    pct = np.where(traded, g["pctChg"], np.nan).astype("float64")
    close = g["close"].astype("float64")
    up, dn = limits(g)
    zt = ok & (np.abs(close - up) < 0.0051)
    dt = ok & (np.abs(close - dn) < 0.0051)
    touched = ok & (g["high"].astype("float64") >= up - 0.0051)
    # 连板
    streak = np.zeros_like(zt, dtype=np.int16)
    for t in range(1, len(zt)):
        streak[t] = (streak[t - 1] + 1) * zt[t]
    streak[0] = zt[0]
    # 复权价（用涨跌幅连乘）
    r = np.where(traded, g["pctChg"] / 100.0, 0.0)
    adj = np.cumprod(1 + r, axis=0)
    adj = np.where(traded, adj, np.nan)
    A = pd.DataFrame(adj)
    hi250 = A.rolling(250, min_periods=200).max().to_numpy()
    lo250 = A.rolling(250, min_periods=200).min().to_numpy()
    ma20 = A.rolling(20, min_periods=15).mean().to_numpy()
    ma60 = A.rolling(60, min_periods=45).mean().to_numpy()
    okh = ok & (age >= 250)
    n_ok = ok.sum(1)
    # 昨日涨停今日表现
    prev_zt = np.vstack([np.zeros((1, zt.shape[1]), bool), zt[:-1]])
    pz = prev_zt & ok
    prem = np.where(pz.sum(1) > 0, np.nansum(np.where(pz, pct, 0), 1) / np.maximum(pz.sum(1), 1), np.nan)
    ew = np.nanmean(np.where(ok, pct, np.nan), 1) / 100
    amt = np.nansum(np.where(traded, g["amount"], 0), 1) / 1e8
    s = pd.DataFrame({
        "n": n_ok,
        "涨停": zt.sum(1), "跌停": dt.sum(1),
        "炸板率": 1 - zt.sum(1) / np.maximum(touched.sum(1), 1),
        "连板高度": np.where(ok, streak, 0).max(1),
        "昨日涨停今日涨幅": prem,
        "上涨占比": (ok & (pct > 0)).sum(1) / np.maximum(n_ok, 1),
        "成交额亿": amt,
        "新高减新低占比": ((okh & (adj >= hi250 - 1e-12)).sum(1) - (okh & (adj <= lo250 + 1e-12)).sum(1)) / np.maximum(okh.sum(1), 1),
        "站上20日线占比": (ok & (adj > ma20)).sum(1) / np.maximum(n_ok, 1),
        "站上60日线占比": (ok & (adj > ma60)).sum(1) / np.maximum(n_ok, 1),
        "等权日收益": ew,
    }, index=g["dates"])
    s["成交额热度"] = s["成交额亿"].rolling(20).mean() / s["成交额亿"].rolling(250).mean()
    s["涨停减跌停"] = s["涨停"] - s["跌停"]
    s["等权指数"] = (1 + s["等权日收益"].fillna(0)).cumprod()
    return s, g, dict(ok=ok, zt=zt, adj=adj, hi250=hi250, ma20=ma20, ma60=ma60, age=age, traded=traded)


if __name__ == "__main__":
    s, g, _ = compute()
    s.to_csv("sentiment_daily.csv")
    pd.set_option("display.width", 250)
    cols = ["n", "涨停", "跌停", "炸板率", "连板高度", "昨日涨停今日涨幅", "上涨占比", "成交额亿", "新高减新低占比", "站上20日线占比"]
    for d in ["2015-06-26", "2015-07-08", "2016-01-04", "2019-02-25", "2024-02-05", "2024-09-30", "2024-10-08", "2025-04-07"]:
        print(d, s.loc[d, cols].round(3).to_dict())
    print(s[cols].describe().round(2).to_string())
