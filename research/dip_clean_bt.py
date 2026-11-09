"""回调企稳做多，只按'企稳后一次买满'这一种做法连续找事件（上一笔平仓后才找下一笔），复核卡片上的成绩。
AMD/美光/戴尔，Dukascopy 交易时段小时线（每天7根），2021-11 → 2026-10。离场：1R后保本，回到跌够那一刻的5天最高价全平，最多10天。
分组：熊市×纳指前一天涨/跌；牛市×纳指前一天收盘已从5天高点跌够2倍日波动（整体回调）/没有。每次100U×5倍。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X, scale_in_bt as SI
from dip_manage_bt import manage, MID, START, END

us = load.us_daily(["^NDX", "QQQ"]); us["date"] = pd.to_datetime(us.date)
px = us.pivot(index="date", columns="ticker", values="close"); n = px["^NDX"].dropna()
sg = np.log(n).diff().rolling(20).std()
ndx = pd.DataFrame({"up": (n > n.shift(1)).astype(float), "dip": (np.log(n / n.rolling(5).max()) <= -2 * sg).astype(float)}).shift(1)
bull = X.bull_daily(px["QQQ"])
TECH = ["AAPL","ADBE","ADI","AMAT","AMZN","AVGO","CRM","CSCO","GOOGL","IBM","INTC","INTU","LRCX","MRVL","MSFT","NFLX","NVDA","ORCL","PYPL","QCOM","TSLA","TXN"]
st = load.dukascopy([s + "USUSD" for s in (TECH if "--tech" in sys.argv else ["AMD", "MU", "DELL"])], start="2021-06")
rows = []
for sym, g in st.groupby("symbol"):
    g = g.sort_values("ts").reset_index(drop=True); bpd = 7; tz = "America/New_York"
    o, h, l, c = (g[x].to_numpy(float) for x in ["open", "high", "low", "close"])
    ts = pd.to_datetime(g.ts, utc=True); day = ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    sig = SI.daily_sigma(g, tz).reindex(day, method="ffill").to_numpy()
    H5 = pd.Series(h).shift(1).rolling(35).max().to_numpy(); H12 = pd.Series(h).shift(1).rolling(4).max().to_numpy()
    N, t = len(c), 36
    while t < N - 1:
        s = sig[t]
        if not (START <= ts[t] < END and np.isfinite(s) and np.isfinite(H5[t]) and c[t] <= H5[t] * np.exp(-2 * s)):
            t += 1; continue
        top, lowest, k = H5[t], l[t], None
        for u in range(t, min(N, t + 35)):
            lowest = min(lowest, l[u])
            if u > t and c[u] > H12[u] and c[u] < top: k = u; break
        if k is None: t += 35; continue
        d = day[k]; b = bull.reindex([d], method="ffill").iloc[0]; nd = ndx.reindex([d], method="ffill").iloc[0]
        pnl, e = manage(o, h, l, c, k, c[k], lowest * np.exp(-0.3 * s), top, bpd, "R0")
        rows.append(dict(sym=sym.replace("USUSD", ""), ts=ts[k], yr=ts[k].year, env="牛市" if b == 1 else "熊市",
                         up=nd.up, ndip=nd.dip, pnl=pnl, half="前段" if ts[k] < MID else "后段"))
        t = max(t + 1, e + 1)
T = pd.DataFrame(rows)
def show(nm, x):
    hm = x.groupby("half").pnl.mean()
    print(f"{nm:<26} {len(x):3d}次 平均 {x.pnl.mean():+6.1f}U 赚的{(x.pnl>0).mean()*100:3.0f}%  前段 {hm.get('前段', np.nan):+6.1f}({(x.half=='前段').sum()}) 后段 {hm.get('后段', np.nan):+6.1f}({(x.half=='后段').sum()})  按年 " +
          " ".join(f"{y}:{v:+.1f}({k})" for (y, v), k in zip(x.groupby('yr').pnl.mean().items(), x.groupby('yr').size())))
B = T[T.env == "熊市"]
show("熊市 全部", B); show("熊市 纳指前一天跌", B[B.up == 0]); show("熊市 纳指前一天涨", B[B.up == 1])
U = T[T.env == "牛市"]
show("牛市 全部", U); show("牛市 纳指整体回调", U[U.ndip == 1]); show("牛市 个股自己跌", U[U.ndip == 0])
