import sys; sys.path.insert(0,"/home/claude/src/Jsq"); sys.path.insert(0,"/home/claude/bt")
import os; os.environ["MARKET_DATA"]="/home/claude/market-data"
import pandas as pd, numpy as np
import stock_bt as S
from market_data import load
d = load.us_daily(S.TECH_2021+S.CHINA, start="2019-06-01")
q = load.us_daily("QQQ", start="2019-01-01").set_index("date")["adj_close"]
qdd = q/q.rolling(252,min_periods=120).max()-1
for X, rearm in [(0.20,0.10),(0.30,0.15)]:
    rows=[]
    for t,g in d.groupby("ticker"):
        px=g.set_index("date")["adj_close"].dropna()
        ma50=px.rolling(50).mean()
        eps,dd=S.episodes(px,X,rearm)
        for i0 in eps:
            if i0+252>=len(px): continue
            p0=px.iloc[i0]; pE=px.iloc[i0+252]
            k2=next((k for k in range(i0,min(i0+252,len(px))) if px.iloc[k]>ma50.iloc[k]),None)
            rows.append(dict(t=t, date=px.index[i0], A=pE/p0-1, Amaxdd=px.iloc[i0:i0+253].min()/p0-1,
                 B2=(pE/px.iloc[k2]-1) if k2 is not None else 0, B2dd=(px.iloc[k2:i0+253].min()/px.iloc[k2]-1) if k2 is not None else 0,
                 mkt_dd=qdd.get(px.index[i0]), mkt_down=qdd.get(px.index[i0])<=-0.10))
    r=pd.DataFrame(rows); r["y"]=r.date.dt.year
    print(f"\n===== 回撤 {X:.0%}  事件 {len(r)}，{r.t.nunique()} 只，按年 {r.y.value_counts().sort_index().to_dict()}")
    def show(sub,name):
        print(f"{name:20s} n={len(sub):3d} | A 12月中位 {sub.A.median():+.0%} 平均 {sub.A.mean():+.0%} 亏钱 {(sub.A<0).mean():.0%} 再跌中位 {sub.Amaxdd.median():.0%} 再跌超20% {(sub.Amaxdd<=-0.2).mean():.0%}"
              f" | B2站上50日线 中位 {sub.B2.median():+.0%} 亏钱 {(sub.B2<0).mean():.0%} 再跌中位 {sub.B2dd.median():.0%}")
    show(r,"全部"); show(r[r.mkt_down],"大盘也跌了10%以上"); show(r[~r.mkt_down],"大盘没怎么跌")
    print(r.groupby("y").agg(n=("A","size"),中位=("A","median"),亏钱=("A",lambda s:(s<0).mean()),再跌中位=("Amaxdd","median")).round(2).to_string())
    print(r.groupby(["y","mkt_down"]).A.agg(["size","median"]).round(2).unstack().to_string())
    r.to_csv(f"stock_split_{int(X*100)}.csv",index=False)
