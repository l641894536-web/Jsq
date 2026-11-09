import pandas as pd, numpy as np, sys
r = pd.read_csv("structure_events.csv"); b = pd.read_csv("structure_base.csv")
bb = b.groupby(["group", "tf"])[["base_up", "base_move"]].mean()
ORDER = ["gold", "silver", "crypto", "stock_main", "stock_other", "stock_nontech", "commod"]
def summ(f, c, g, tf):
    w, l_ = f.r[f.r > 0], f.r[f.r <= 0]
    bu, bm = bb.loc[(g, tf)]
    long = f.side == 1
    base_right = np.where(long, bu, 1 - bu).mean()
    base_mv = np.where(long, bm, -bm).mean()
    return dict(n=len(f), 方向对=round(f.right24.mean()*100,1), 任意时刻=round(base_right*100,1),
                走几倍ATR=round(f.move24.mean(),2), 任意走=round(base_mv,2),
                胜率=round((f.r>0).mean()*100), 赢均=round(w.mean(),2), 输均=round(l_.mean(),2),
                每笔R=round(f.r.mean(),3), h1=round(f[f.half=="h1"].r.mean(),3), h2=round(f[f.half=="h2"].r.mean(),3),
                对照R=round(c.r.mean(),3))
rows = []
for g in ORDER:
    for tf in ["4h", "1h", "15m"]:
        x = r[(r.group == g) & (r.tf == tf)]
        if x.empty: continue
        f, c = x[x.kind == "flip"], x[x.kind == "ctrl"]
        rows.append(dict(组=g, 周期=tf, 环境="全部", 方向="多空", **summ(f, c, g, tf)))
        for env in ["bull", "bear"]:
            for d in ["long", "short"]:
                ff, cc = f[(f.env == env) & (f.dir == d)], c[(c.env == env) & (c.dir == d)]
                if len(ff) < 30: continue
                rows.append(dict(组=g, 周期=tf, 环境=env, 方向=d, **summ(ff, cc, g, tf)))
t = pd.DataFrame(rows)
t.to_csv("structure_summary.csv", index=False)
pd.set_option("display.width", 250)
print(t[t.环境 == "全部"].drop(columns=["环境", "方向"]).to_string(index=False))
print()
print(t[t.环境 != "全部"].to_string(index=False))
