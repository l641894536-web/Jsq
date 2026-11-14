"""接 holder_bt.py：加仓放在哪里更好（下跌途中 vs 反弹出来后），以及拿着时用"跌破这轮最低价就走"能不能少受伤。
都按"起点时手里1份"算美元盈亏（单位=起点那1份的钱），250天后。"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
from rally_dip_bt import panel_a, panel_us
H = 250; START, MID = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-15")


def run(dates, adjf, U, ew, lab):
    T, N = adjf.shape
    hi250 = pd.DataFrame(adjf).rolling(250, min_periods=200).max().to_numpy()
    rows = []; t0 = dates.searchsorted(START)
    for j in range(N):
        c = adjf[:, j]; ratio = c / hi250[:, j]
        i = max(t0, 260); last = -999
        while i < T - H:
            if not (U[i, j] and ratio[i] <= 0.70 and np.nanmax(ratio[i - 60:i]) >= 0.75 and i - last > 60):
                i += 1; continue
            last = i; p0 = c[i]; end = i + H
            seg = c[i:end + 1]
            # 第一波反弹 / 二次确认 / 反弹后又破低
            L = p0; E1 = None; E2 = None; P = None; pulled = False; brk = None; L1 = None
            for t in range(i + 1, end + 1):
                x = c[t]
                if not np.isfinite(x): continue
                if E1 is None:
                    L = min(L, x)
                    if x >= L * 1.15: E1 = t; P = x; L1 = L
                else:
                    if brk is None and x < L1: brk = t
                    if E2 is None and brk is None:
                        if not pulled:
                            if x > P: P = x
                            elif x <= P * 0.92: pulled = True
                        elif x > P: E2 = t
            cE = c[end]
            pnl = lambda units, cost: units * cE / p0 - cost / p0      # 以起点1份的钱为单位
            r = {"d": dates[i], "hold": pnl(1, p0)}
            # 下跌途中加：跌10%、20%各加1份
            u, cst = 1.0, p0
            for lvl in (0.9, 0.8):
                h = np.where(seg[1:] <= p0 * lvl)[0]
                if len(h): u += 1; cst += seg[1 + h[0]]
            r["add_dn"] = pnl(u, cst); r["add_dn_units"] = u
            r["add_dn_worst"] = np.nanmin([(u_ * c[t] - cs_) / p0 for t, u_, cs_ in [(t, *(lambda tt: (1 + sum(1 for l in (0.9, 0.8) if np.nanmin(seg[1:tt - i + 1]) <= p0 * l) if tt > i else 1,
                                                                                                        p0 + sum(seg[1 + np.where(seg[1:] <= p0 * l)[0][0]] for l in (0.9, 0.8) if tt > i and np.nanmin(seg[1:tt - i + 1]) <= p0 * l)))(t)) for t in range(i, end + 1, 5)]])
            # 反弹出来后加：第一波反弹时加2份
            if E1 is not None:
                r["add_e1"] = pnl(3, p0 + 2 * c[E1])
            else:
                r["add_e1"] = r["hold"]
            # 拿着 + 第一波反弹后跌破这轮最低价就走（不再买回）
            if E1 is not None and brk is not None:
                r["hold_stopL"] = c[brk] / p0 - 1
            else:
                r["hold_stopL"] = r["hold"]
            # 第一波反弹加2份 + 跌破这轮最低价全走
            if E1 is not None:
                if brk is not None:
                    r["e1_stopL"] = (3 * c[brk] - p0 - 2 * c[E1]) / p0
                else:
                    r["e1_stopL"] = r["add_e1"]
            else:
                r["e1_stopL"] = r["hold"]
            r["broke"] = E1 is not None and brk is not None
            rows.append(r); i += 60
    R = pd.DataFrame(rows); R["per"] = np.where(R.d < MID, "前半", "后半")
    pct = lambda v: f"{v*100:+.1f}%"
    print(f"\n######## {lab}：{len(R):,} 次被套30%。第一波反弹后又跌破这轮最低价的 {R.broke.mean():.0%}")
    out = []
    for nm, col in [("死扛（1份）", "hold"), ("拿着，反弹后跌破这轮最低价就走", "hold_stopL"),
                    ("下跌途中加（跌10%、20%各加1份）", "add_dn"), ("反弹出来再加（从低点涨15%时加2份）", "add_e1"), ("反弹出来再加 + 跌破这轮最低价全走", "e1_stopL")]:
        x = R[col]
        out.append({"做法": nm, "250天后盈亏(按1份算)": pct(x.mean()), "中位数": pct(x.median()), "最差10%": pct(x.quantile(.1)), "最差1%": pct(x.quantile(.01)),
                    "前半": pct(x[R.per == '前半'].mean()), "后半": pct(x[R.per == '后半'].mean())})
    print(pd.DataFrame(out).to_string(index=False))
    print(f"下跌途中加：平均加到 {R.add_dn_units.mean():.1f} 份，期间账面最多亏（按1份算）平均 {pct(R.add_dn_worst.mean())}，最差10% {pct(R.add_dn_worst.quantile(.1))}")
    return R


RA = run(*panel_a(), "A股"); RU = run(*panel_us(), "美股")
pd.to_pickle({"A": RA, "US": RU}, "/home/claude/bt/_holder2.pkl")
