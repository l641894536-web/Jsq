import numpy as np, pandas as pd, sys
sys.path.insert(0, "/home/claude/bt")
from rally_dip_bt import panel_a, panel_us
H = 250; START, MID = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-15")
def run(dates, adjf, U, ew, lab):
    T, N = adjf.shape
    hi250 = pd.DataFrame(adjf).rolling(250, min_periods=200).max().to_numpy()
    res = {x: [] for x in (0, 0.10, 0.15, 0.20, 0.25)}; t0 = dates.searchsorted(START)
    for j in range(N):
        c = adjf[:, j]; ratio = c / hi250[:, j]; i = max(t0, 260); last = -999
        while i < T - H:
            if not (U[i, j] and ratio[i] <= 0.70 and np.nanmax(ratio[i - 60:i]) >= 0.75 and i - last > 60):
                i += 1; continue
            last = i; end = i + H; per = "前半" if dates[i] < MID else "后半"
            for x in res:
                if x == 0: k = i
                else:
                    L = c[i]; k = None
                    for t in range(i + 1, end + 1):
                        if not np.isfinite(c[t]): continue
                        L = min(L, c[t])
                        if c[t] >= L * (1 + x): k = t; break
                if k is None: continue
                w = c[k + 1:min(k + 61, T)]
                res[x].append((c[end] / c[k] - 1, np.nanmin(w) < c[k] * 0.9, per))
            i += 60
    print(lab)
    for x, v in res.items():
        d = pd.DataFrame(v, columns=["r", "trap", "per"])
        print(f"  {'跌30%就买' if x==0 else f'从低点涨{int(x*100)}%买':10s} 平均 {d.r.mean()*100:+.1f}% 亏钱{(d.r<0).mean():.0%} 买后60天再跌10% {d.trap.mean():.0%}  前后 {d[d.per=='前半'].r.mean()*100:+.1f}/{d[d.per=='后半'].r.mean()*100:+.1f}  套 {d[d.per=='前半'].trap.mean():.0%}/{d[d.per=='后半'].trap.mean():.0%}")
run(*panel_a(), "A股"); run(*panel_us(), "美股")
