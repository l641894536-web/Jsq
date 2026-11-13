import numpy as np, pandas as pd
import os; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_entry_check.py")).read().split("X = pd.DataFrame(rows)")[0].replace('for name in ["S0", "S2", "S3", "S4"]:', 'for name in ["S0", "S4", "S5"]:').replace(
 'if name == "S4" and qa[k] < qma[k]: k_out = k; break',
 'if name == "S4" and qa[k] < qma[k]: k_out = k; break\n                if name == "S5":\n                    if bc is None and qa[k] < qma[k] * 0.98: bc = qa[k]\n                    if bc is not None and qa[k] < bc * 0.85: k_out = k; break').replace(
 'k_out = end; peak = Pa[i, j]', 'k_out = end; peak = Pa[i, j]; bc = None'))
X = pd.DataFrame(rows); mid = sorted(X.d.unique())[len(X.d.unique()) // 2]
B = X.groupby("d")[["S0", "S4", "S5"]].mean()
for s in ["S0", "S4", "S5"]:
    print(s, f"单只平均 {X[s].mean()*100:+.1f}%  篮子平均 {B[s].mean()*100:+.1f}%  篮子最差 {B[s].min()*100:+.1f}%  篮子亏钱月 {(B[s]<0).sum()}/{len(B)}")
