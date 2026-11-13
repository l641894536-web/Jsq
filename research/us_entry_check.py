import numpy as np, pandas as pd
import os; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_entry_bt.py")).read().split("recs, exits = [], []")[0])
rows = []
for d in months:
    i = days.get_loc(d)
    if i + 140 >= len(days) or not bool(bull.loc[d]):
        continue
    snap = g[(g.filed < d) & (g.end > d - pd.Timedelta(days=200))].sort_values("end").groupby(["ticker", "kind"]).last()
    rev = snap.xs("rev", level="kind"); ni = snap.xs("ni", level="kind")
    uni = [t for t in rev.index if t in P.columns and np.isfinite(P.iloc[i][t]) and np.isfinite(P.iloc[i - 120][t])]
    r = rev.loc[uni].yoy; n = ni.reindex(uni).yoy; mom = (P.iloc[i][uni] / P.iloc[i - 120][uni] - 1)
    pick = [t for t in uni if r[t] >= r.quantile(.7) and np.isfinite(n[t]) and n[t] >= n.quantile(.7) and mom[t] > mom.quantile(.3)]
    for t in pick:
        j = cols.index(t)
        ic = next((k for k in range(i, i + 20) if Pa[k, j] > h20[k, j]), None)
        end = i + 120
        rec = {"d": d, "t": t, "C_trig": ic is not None,
               "A60": fwd(j, i), "C60": fwd(j, ic) if ic is not None else np.nan,
               "ew120": ew[end] / ew[i] - 1}
        # 120天固定窗口，卖出后拿现金
        for name in ["S0", "S2", "S3", "S4"]:
            k_out = end; peak = Pa[i, j]
            for k in range(i + 1, end + 1):
                if not np.isfinite(Pa[k, j]): continue
                peak = max(peak, Pa[k, j])
                if name == "S2" and Pa[k, j] < m50[k, j]: k_out = k; break
                if name == "S3" and Pa[k, j] <= peak * 0.85: k_out = k; break
                if name == "S4" and qa[k] < qma[k]: k_out = k; break
            rec[name] = Pa[k_out, j] / Pa[i, j] - 1
            rec[name + "_dd"] = np.nanmin(Pa[i:k_out + 1, j]) / Pa[i, j] - 1
        # C 进场后用 S2 卖、窗口同样到 end（进场前拿现金）
        if ic is not None:
            k_out = end
            for k in range(ic + 1, end + 1):
                if np.isfinite(Pa[k, j]) and Pa[k, j] < m50[k, j]: k_out = k; break
            rec["C_S2"] = Pa[k_out, j] / Pa[ic, j] - 1
            rec["C_S0"] = Pa[end, j] / Pa[ic, j] - 1
        rows.append(rec)
X = pd.DataFrame(rows); mid = sorted(X.d.unique())[len(X.d.unique()) // 2]
c = X[X.C_trig]
print(f"同一批（当月出现20日新高的 {len(c)}/{len(X)} 次）：月初买60天 {c.A60.mean()*100:+.2f}%  等新高买60天 {c.C60.mean()*100:+.2f}%")
print(f"   前后：月初 {c[c.d<mid].A60.mean()*100:+.2f}/{c[c.d>=mid].A60.mean()*100:+.2f}  新高 {c[c.d<mid].C60.mean()*100:+.2f}/{c[c.d>=mid].C60.mean()*100:+.2f}")
nc = X[~X.C_trig]; print(f"当月没出新高的 {len(nc)} 次：月初买60天 {nc.A60.mean()*100:+.2f}%")
print(f"\n120天同一窗口（卖了拿现金），样本等权同期 {X.ew120.mean()*100:+.2f}%：")
for s, lab in [("S0", "一直拿120天"), ("S2", "跌破50日线卖"), ("S3", "回撤15%卖"), ("S4", "纳指破200日线卖")]:
    print(f"  {lab:12s} 平均 {X[s].mean()*100:+.2f}%  中位 {X[s].median()*100:+.2f}%  最差10% {X[s].quantile(.1)*100:+.1f}%  持有期最大浮亏(平均) {X[s+'_dd'].mean()*100:.1f}%  前后 {X[X.d<mid][s].mean()*100:+.2f}/{X[X.d>=mid][s].mean()*100:+.2f}")
print(f"  等新高买+破50日线卖 平均 {c.C_S2.mean()*100:+.2f}%  最差10% {c.C_S2.quantile(.1)*100:+.1f}% ；等新高买一直拿 {c.C_S0.mean()*100:+.2f}%")
B = X.groupby("d").agg(n=("S0", "size"), s0=("S0", "mean"), s4=("S4", "mean"), ew=("ew120", "first"))
print(f"\n整篮子（每月名单等权，平均 {B.n.mean():.0f} 只）120天：平均 {B.s0.mean()*100:+.1f}%  最差月 {B.s0.min()*100:+.1f}%  跑输等权的月 {(B.s0<B.ew).sum()}/{len(B)}  亏钱的月 {(B.s0<0).sum()}/{len(B)}")
print(B.sort_values("s0").head(4).assign(s0=lambda b: (b.s0*100).round(1), ew=lambda b: (b.ew*100).round(1)))
