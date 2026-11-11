"""做空打法放到更长的历史里看（2000 起）：真正的大熊市（2000-02、2008-09、2022）里做空个股到底行不行。
注意：股票库是今天还活着、还热门的股票，当年跌没了的不在里面，所以做空的成绩被低估。"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load
import short_range_bt as S
S.START = pd.Timestamp("1999-06-01")
U = load.us_daily(start="1998-01-01"); f = U.adj_close / U.close
for k in ("open", "high", "low", "close"): U[k] = U[k] * f
q = U[U.ticker == "QQQ"].set_index("date").close; q200 = S.above(q, 200)
rows = []
for tk, g in U.groupby("ticker"):
    if "=" in tk or "^" in tk or "-" in tk or len(g) < 400 or (tk in S.ETF and tk not in ("QQQ", "SPY")): continue
    rows += S.run(tk, "指数" if tk in ("QQQ", "SPY") else "个股", "日线", g.set_index("date")[["open", "high", "low", "close", "volume"]], q200)
T = pd.DataFrame(rows, columns=["grp", "tf", "inst", "method", "ts", "big", "st", "u", "risk"]); T.to_csv("short_long_hist.csv.gz", index=False)
T = T[T.method.str.endswith("_S")]
def fam(m):
    b = m.rsplit("_", 1)[0]
    return "过热后转弱" if b.startswith("heat") else "反弹失败" if b in ("fail_rally", "lower_high") else "震荡回归" if b in ("bb_rev", "rsi2", "edge", "fakeout") else "收窄后突破" if b == "squeeze" else "利空跳空"
T["fam"] = T.method.map(fam)
era = lambda d: "2000-02大熊" if d < pd.Timestamp("2003-04-01") else "2003-07" if d < pd.Timestamp("2008-01-01") else "2008-09大熊" if d < pd.Timestamp("2009-07-01") else "2009-21" if d < pd.Timestamp("2022-01-01") else "2022熊" if d < pd.Timestamp("2023-02-01") else "2023-26"
T["era"] = T.ts.map(era); T["big"] = T.big.map({True: "牛", False: "熊"})
def summ(g):
    d = g.groupby("ts").u.mean()
    return pd.Series({"笔": len(g), "信号日": len(d), "u": round(g.u.mean(), 2), "胜%": round((g.u > 0).mean() * 100), "t": round(d.mean() / d.std() * np.sqrt(len(d)), 1) if len(d) > 2 else 0})
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 300)
print(T[T.big == "熊"].groupby(["grp", "fam", "era"]).apply(summ).to_string())
print("\n纳指熊市期间，全部做空打法合计，按时期:"); print(T[T.big == "熊"].groupby(["grp", "era"]).apply(summ).to_string())
print("\n同期股票数（有多少只那时已上市）:", T.groupby("era").inst.nunique().to_dict())
