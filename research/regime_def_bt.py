"""牛熊用什么分？同一批小时线突破单（出场F：1R保本+跟踪3天低点），换不同的'大方向'定义，看做多/做空各自赚不赚。
参照：黄金=GC=F、白银=SI=F、美股=QQQ、币=比特币日线；都用进场前一天的收盘判断（不偷看）。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
E = pd.read_csv("exit_trades.csv", parse_dates=["ts"]); E = E[E.v == "F"].copy()
us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
px = us.pivot(index="date", columns="ticker", values="close")
b = load.binance("1h", ["BTCUSDT"], start="2019-01-01"); btc = b.set_index(b.ts.dt.tz_localize(None)).close.resample("1D").last().dropna()
REF = {"黄金": px["GC=F"].dropna(), "白银": px["SI=F"].dropna(), "AMD/美光/戴尔": px["QQQ"].dropna(), "其他科技股": px["QQQ"].dropna(), "加密": btc}
def flags(s):
    m50, m100, m200 = s.rolling(50).mean(), s.rolling(100).mean(), s.rolling(200).mean()
    up200 = m200 > m200.shift(20)
    f = pd.DataFrame({
        "200日线（现在用的）": np.where(s > m200, 1, -1),
        "200日线+线的方向": np.where((s > m200) & up200, 1, np.where((s < m200) & ~up200, -1, 0)),
        "50日线在200日线上/下（金叉死叉）": np.where(m50 > m200, 1, -1),
        "100日线": np.where(s > m100, 1, -1),
        "50日线": np.where(s > m50, 1, -1)}, index=s.index)
    return f.shift(1)       # 只用前一天收盘
rows = []
for g, s in REF.items():
    F = flags(s); x = E[E.grp == g].copy()
    d = x.ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    for k in F.columns:
        x[k] = F[k].reindex(d, method="ffill").to_numpy()
    for k in F.columns:
        for dr, want, nm in (("long", 1, "顺势做多"), ("short", -1, "顺势做空")):
            y = x[(x.dir == dr) & (x[k] == want)]
            if len(y) < 20: continue
            hm = y.groupby("half").r.mean()
            rows.append(dict(品种=g, 定义=k, 方向=nm, 笔数=len(y), 平均=round(y.r.mean(), 3), 前段=round(hm.get("h1", np.nan), 3), 后段=round(hm.get("h2", np.nan), 3)))
    # 做空按年（现在的定义，熊市里做空）
    y = x[(x.dir == "short") & (x["200日线（现在用的）"] == -1)]
    print(g, "熊市做空按年:", y.groupby(y.ts.dt.year).r.agg(["size", "mean"]).round(2).to_dict("index"))
R = pd.DataFrame(rows); pd.set_option("display.width", 250)
print(R.to_string(index=False))
R.to_csv("regime_def_report.csv", index=False)
