import numpy as np, pandas as pd
import os; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_entry_bt.py")).read().split("recs, exits = [], []")[0])
HI = P.rolling(252, min_periods=150).max().to_numpy(); M200 = P.rolling(200, min_periods=150).mean().to_numpy()
rows = []
for d in months:
    i = days.get_loc(d)
    if i + H >= len(days) or not bool(bull.loc[d]): continue
    snap = g[(g.filed < d) & (g.end > d - pd.Timedelta(days=200))].sort_values("end").groupby(["ticker", "kind"]).last()
    rev = snap.xs("rev", level="kind"); ni = snap.xs("ni", level="kind")
    uni = [t for t in rev.index if t in P.columns and np.isfinite(P.iloc[i][t]) and np.isfinite(P.iloc[i - 120][t])]
    r = rev.loc[uni].yoy; n = ni.reindex(uni).yoy; mom = (P.iloc[i][uni] / P.iloc[i - 120][uni] - 1)
    for t in uni:
        j = cols.index(t)
        grow = r[t] >= r.quantile(.7) and np.isfinite(n[t]) and n[t] >= n.quantile(.7)
        rows.append({"d": d, "t": t, "grow": grow, "weak": mom[t] <= mom.quantile(.3), "dd": Pa[i, j] / HI[i, j] - 1,
                     "a200": Pa[i, j] > M200[i, j], "x": fwd(j, i)})
X = pd.DataFrame(rows).dropna(subset=["x"]); mid = sorted(X.d.unique())[len(X.d.unique()) // 2]
def show(lab, m):
    y = X[m]; bym = y.groupby("d").x.mean()
    print(f"{lab:28s} {len(y):4d}次 60天超额 {y.x.mean()*100:+.2f}%  月份跑赢 {(bym>0).sum()}/{len(bym)}  前后 {y[y.d<mid].x.mean()*100:+.2f}/{y[y.d>=mid].x.mean()*100:+.2f}")
G = X.grow & ~X.weak
show("名单（全部）", G)
show("名单·离一年高点不到30%", G & (X.dd > -0.3))
show("名单·跌了30%以上", G & (X.dd <= -0.3))
show("名单·跌了30%以上·仍在200日线上", G & (X.dd <= -0.3) & X.a200)
show("名单·跌了30%以上·在200日线下", G & (X.dd <= -0.3) & ~X.a200)
show("名单·在200日线下", G & ~X.a200)
show("非名单·跌了30%以上", ~G & (X.dd <= -0.3))
