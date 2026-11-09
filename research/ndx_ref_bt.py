"""回调企稳做多（dip_v2_bt 的 F：企稳后一次买满 / S：企稳后先30%赚了再加），按纳指100当时的状态分组：
  大盘一起跌：纳指前一交易日收盘离5天最高 ≥ 2 倍纳指日波动（整体回调） vs 没有（个股自己跌）
  纳指前一天：涨 vs 跌（大盘是否先企稳）
  VIX 前一天 ≥ 25（恐慌） vs < 25
都只用进场当天之前的收盘。AMD/美光/戴尔 + 22只科技股复核，牛熊分开，前后两段。每次 100U×5倍。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import dip_v2_bt as V, exit_bt as X, scale_in_bt as SI

us = load.us_daily(["^NDX", "^VIX", "QQQ"]); us["date"] = pd.to_datetime(us.date)
px = us.pivot(index="date", columns="ticker", values="close")
n = px["^NDX"].dropna()
lr = np.log(n).diff(); sig = lr.rolling(20).std()
ndx = pd.DataFrame({"dip": (np.log(n / n.rolling(5).max()) <= -2 * sig).astype(int), "up": (n > n.shift(1)).astype(int),
                    "vix": (px["^VIX"].reindex(n.index) >= 25).astype(int)})
bull = X.bull_daily(px["QQQ"])
main3 = ["AMD", "MU", "DELL"]
tech = ["AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX", "MRVL",
        "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN"]
st = load.dukascopy([s + "USUSD" for s in main3 + tech], start="2021-06")
allt = []
for sym, g in st.groupby("symbol"):
    tk = sym.replace("USUSD", "")
    t = V.run_sym(g[["ts", "open", "high", "low", "close"]], 7, SI.daily_sigma(g, "America/New_York"), "America/New_York", 2)
    t = t[t.kts.notna()].copy()
    d = pd.to_datetime(t.kts, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    prev = ndx.shift(1).reindex(d, method="ffill")            # 进场当天之前最近一个收盘
    for c in ndx.columns:
        t[c] = prev[c].to_numpy()
    bb = bull.reindex(d, method="ffill").to_numpy()
    t["env"] = np.where(pd.isna(bb), None, np.where(bb == 1, "牛市", "熊市"))
    allt.append(t.assign(grp="AMD/美光/戴尔" if tk in main3 else "其他22只科技股", sym=tk))
T = pd.concat(allt, ignore_index=True); T = T[T.env.notna()]
T["half"] = np.where(pd.to_datetime(T.kts, utc=True) < V.MID, "前段", "后段")
T.to_csv("ndx_ref_trades.csv", index=False)
rows = []
LAB = {"dip": ("纳指也跌够了(整体回调)", "纳指没怎么跌(个股自己跌)"), "up": ("纳指前一天涨", "纳指前一天跌"), "vix": ("VIX≥25", "VIX<25")}
for (g, e), x in T.groupby(["grp", "env"]):
    for m in ("F", "S"):
        base = x[f"pnl_{m}"].dropna()
        rows.append(dict(品种=g, 环境=e, 做法={"F": "企稳一次买满", "S": "企稳30%赚了再加"}[m], 条件="不加条件", 次数=len(base), 每次平均U=round(base.mean(), 2),
                         前段=round(x[x.half == "前段"][f"pnl_{m}"].mean(), 2), 后段=round(x[x.half == "后段"][f"pnl_{m}"].mean(), 2), 赚的比例=round((base > 0).mean() * 100),
                         股票为正=f"{(x.groupby('sym')[f'pnl_{m}'].mean() > 0).sum()}/{x.sym.nunique()}"))
        for c, (a, b) in LAB.items():
            for val, nm in ((1, a), (0, b)):
                y = x[x[c] == val]; p = y[f"pnl_{m}"].dropna()
                if len(p) < 10:
                    continue
                rows.append(dict(品种=g, 环境=e, 做法={"F": "企稳一次买满", "S": "企稳30%赚了再加"}[m], 条件=nm, 次数=len(p), 每次平均U=round(p.mean(), 2),
                                 前段=round(y[y.half == "前段"][f"pnl_{m}"].mean(), 2), 后段=round(y[y.half == "后段"][f"pnl_{m}"].mean(), 2),
                                 赚的比例=round((p > 0).mean() * 100), 股票为正=f"{(y.groupby('sym')[f'pnl_{m}'].mean() > 0).sum()}/{y.sym.nunique()}"))
pd.set_option("display.width", 250)
R = pd.DataFrame(rows)
R.to_csv("ndx_ref_report.csv", index=False)
print(R[R.做法 == "企稳一次买满"].to_string(index=False))
