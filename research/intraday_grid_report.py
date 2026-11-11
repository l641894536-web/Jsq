import pandas as pd, numpy as np
t = pd.read_csv("intraday_grid_trades.csv.gz", parse_dates=["ts"])
mid = t.groupby("inst").ts.transform(lambda s: s.sort_values().iloc[len(s)//2])
t["half"] = np.where(t.ts < mid, 1, 2)
def summ(g):
    a, b = g[g.half == 1].u, g[g.half == 2].u
    return pd.Series({"n": len(g), "u": round(g.u.mean(), 2), "win%": round((g.u > 0).mean()*100), "h1": round(a.mean(), 2) if len(a) else np.nan,
                      "h2": round(b.mean(), 2) if len(b) else np.nan, "n1": len(a), "n2": len(b),
                      "t": round(g.u.mean()/g.u.std()*np.sqrt(len(g)), 1) if len(g) > 2 else 0})
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 600)
ST = {1: "小时涨", -1: "小时跌", 0: "横盘"}
t["st"] = t.st.map(ST); t["big"] = t.big.map({True: "牛", False: "熊"}); t["side"] = t.side.map({1: "多", -1: "空"})
print("总笔数", len(t), "全部平均", round(t.u.mean(), 2))
print("\n== 1. 各方法总体（不分行情）=="); print(t.groupby(["grp", "method", "side", "exit"]).apply(summ).unstack("exit")[["u"]].to_string())
c1 = t.groupby(["grp", "big", "st", "method", "side", "exit"]).apply(summ).reset_index()
c1.to_csv("intraday_grid_by_group.csv", index=False)
good = c1[(c1.n >= 150) & (c1.h1 > 0) & (c1.h2 > 0) & (c1.t >= 3) & (c1.n1 >= 50) & (c1.n2 >= 50)].sort_values("t", ascending=False)
print("\n== 2. 按品种组：前后两段都赚、t>=3 的格子（共 %d 格里的 %d 格）==" % (len(c1), len(good))); print(good.to_string(index=False))
c2 = t.groupby(["inst", "big", "st", "method", "side", "exit"]).apply(summ).reset_index()
c2.to_csv("intraday_grid_by_inst.csv", index=False)
g2 = c2[(c2.n >= 80) & (c2.h1 > 0) & (c2.h2 > 0) & (c2.t >= 3)].sort_values("t", ascending=False)
print("\n== 3. 按单个标的：过关格子（共 %d 格里的 %d 格；纯碰运气约 %.0f 格）==" % (len(c2), len(g2), len(c2)*0.00135*0.5)); print(g2.head(60).to_string(index=False))
print("\n== 4. 最差的格子（反着做也没用，只是提醒别做）=="); print(c1[c1.n >= 300].sort_values("t").head(12).to_string(index=False))
