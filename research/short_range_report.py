import pandas as pd, numpy as np
T = pd.read_csv("short_range_trades.csv.gz"); T["ts"] = pd.to_datetime(T.ts, format="mixed")
T["big"] = T.big.map({True: "牛", False: "熊"}); mid = pd.Timestamp("2024-05-01")
def summ(g):
    d = g.groupby("ts").u.mean(); a, b = d[d.index < mid], d[d.index >= mid]
    return pd.Series({"笔": len(g), "信号日": len(d), "u": round(g.u.mean(), 2), "胜%": round((g.u > 0).mean() * 100), "前": round(a.mean(), 2) if len(a) else np.nan, "后": round(b.mean(), 2) if len(b) else np.nan,
                      "日1": len(a), "日2": len(b), "最差5%": round(g.u.quantile(0.05), 1), "R": round((g.u / 500 / g.risk).mean(), 2),
                      "t": round(d.mean() / d.std() * np.sqrt(len(d)), 1) if len(d) > 2 and d.std() > 0 else 0})
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 600)
R = T.groupby(["grp", "tf", "big", "st", "method"]).apply(summ).reset_index(); R.to_csv("short_range_report.csv", index=False)
R2 = T.groupby(["grp", "tf", "big", "method"]).apply(summ).reset_index(); R2.insert(3, "st", "全部"); R2.to_csv("short_range_report_nost.csv", index=False)
A = pd.concat([R, R2])
ok = A[(A.信号日 >= 40) & (A.前 > 0) & (A.后 > 0) & (A.t >= 3) & (A.日1 >= 12) & (A.日2 >= 12)].sort_values("t", ascending=False)
print("格子总数", len(A), " 过关", len(ok), " 纯运气预期约", round(len(A) * 0.00135 * 0.5, 1))
print("\n== 过关的（前后两段都赚、按信号日 t>=3）=="); print(ok.to_string(index=False))
sh = A[A.method.str.endswith("_S") & (A.信号日 >= 30)]
print("\n== 做空类：熊市里各组最好的（不管过没过关）=="); print(sh[sh.big == "熊"].sort_values("t", ascending=False).head(25).to_string(index=False))
print("\n== 做空类：牛市里最好的 =="); print(sh[sh.big == "牛"].sort_values("t", ascending=False).head(10).to_string(index=False))
rg = A[(A.st == "横盘") & (A.信号日 >= 30)]
print("\n== 横盘状态下最好的 =="); print(rg.sort_values("t", ascending=False).head(25).to_string(index=False))
print("\n== 横盘状态下最差的 =="); print(rg.sort_values("t").head(8).to_string(index=False))
print("\n== 各方法总体（所有标的所有行情）=="); print(T.groupby("method").u.agg(["size", "mean"]).round(2).sort_values("mean").T.to_string())
