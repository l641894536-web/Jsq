import numpy as np, pandas as pd
F = pd.read_pickle("_factors.pkl"); z = np.load("_factor_base.npz", allow_pickle=True)
R, fwd, U, bull, per = z["R"], z["fwd"], z["U"], z["bull"], z["per"]
def qx(X, k, good):
    m = U[k] & np.isfinite(X[k])
    if m.sum() < 300: return np.nan
    x, y = X[k, m], fwd[k, m]; base = np.nanmean(fwd[k, U[k]])
    lo, hi = np.nanquantile(x, [0.2, 0.8]); s = y[x >= hi] if good > 0 else y[x <= lo]
    return np.nanmean(s) - base
rows = []
for name, good in [("总市值", -1), ("换手放大(20日/一年)", -1), ("站上200日线", -1), ("站上60日线", -1), ("近20日涨幅", -1), ("离一年高点", -1),
                   ("净利润增速变化", 1), ("净资产收益比(1/PB)", 1), ("20日涨停次数", -1), ("60日波动", -1), ("净利润增速", 1), ("一年动量(去掉近一月)", 1)]:
    v = np.array([qx(F[name], k, good) for k in range(len(R))])
    r = {"指标": name, "好": "高" if good > 0 else "低"}
    for lab, m in [("牛·前半", (per == "前半") & bull), ("牛·后半", (per == "后半") & bull), ("牛·16-21", (per == "2016-21") & bull),
                   ("熊·前半", (per == "前半") & ~bull), ("熊·后半", (per == "后半") & ~bull), ("熊·16-21", (per == "2016-21") & ~bull)]:
        w = v[m]; w = w[np.isfinite(w)]; r[lab] = f"{w.mean()*100:+.2f}({len(w)})" if len(w) else "—"
    rows.append(r)
pd.set_option("display.width", 250); print(pd.DataFrame(rows).to_string(index=False))
