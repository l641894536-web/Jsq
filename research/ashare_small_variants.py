import numpy as np, pandas as pd
import os; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ashare_small_bt.py")).read().split("W5 = per != \"2016-21\"")[0])
ep = F["盈利收益率(1/PE)"]; zt20 = F["20日涨停次数"]; mx = F["20日最大单日涨幅"]; acc = F["净利润增速变化"]; dd = F["离一年高点"]
def run2(filt, n=30, cost=0.0025, bullacc=False):
    rets, prev = [], set()
    for k in range(len(R)):
        m = U0[k] & (amt20[k] >= 3e7) & np.isfinite(size[k]) & np.isfinite(fwd[k]) & filt(k)
        ok = np.where(m)[0]
        if bullacc and bull[k]:
            cut = np.nanquantile(size[k][ok], 0.2); c2 = ok[size[k][ok] <= cut]; a = acc[k][c2]
            c2 = c2[np.isfinite(a)]; a = acc[k][c2]; idx = c2[np.argsort(-a)[:n]] if len(c2) >= n else ok[np.argsort(size[k][ok])[:n]]
        else:
            idx = ok[np.argsort(size[k][ok])[:n]]
        cur = set(idx.tolist()); turn = 1 - len(cur & prev) / n if prev else 1.0
        rets.append(np.nanmean(fwd[k, idx]) - cost * turn); prev = cur
    return np.array(rets)
W5 = per != "2016-21"
V2 = {"最小30只": run2(lambda k: np.ones(fwd.shape[1], bool)),
      "去掉亏损股(PE<0)": run2(lambda k: np.nan_to_num(ep[k], nan=-1) > 0),
      "去掉近20天涨停≥2次": run2(lambda k: ~(np.nan_to_num(zt20[k]) >= 2)),
      "去掉离高点跌60%以上": run2(lambda k: np.nan_to_num(dd[k], nan=0) > -0.6),
      "牛市在最小20%里挑增速加快": run2(lambda k: np.ones(fwd.shape[1], bool), bullacc=True),
      "去亏损+去近20天涨停≥2": run2(lambda k: (np.nan_to_num(ep[k], nan=-1) > 0) & ~(np.nan_to_num(zt20[k]) >= 2))}
for k, r in V2.items():
    a5, dd5, mn5 = st(r, W5); a1, _, _ = st(r, per == "前半"); a2, _, _ = st(r, per == "后半"); a0, dd0, _ = st(r, per == "2016-21")
    y = pd.Series(r).groupby(yr).apply(lambda s: np.prod(1 + s) - 1)
    print(f"{k:22s} 5年 {a5*100:+.1f}% 回撤 {dd5*100:.1f}% 前后 {a1*100:+.1f}/{a2*100:+.1f} 2016-21 {a0*100:+.1f}%(回撤{dd0*100:.0f}%) 2024 {y[2024]*100:+.1f} 2026 {y[2026]*100:+.1f} 跑赢等权 {int(((r-ew)[W5]>0).sum())}/60")
pd.to_pickle(V2, "/home/claude/bt/_small_var.pkl")
