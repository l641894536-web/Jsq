"""美股成长名单（营收、净利润同比都在样本前30%，去掉近半年最弱30%）：什么时候买更好？
每月第一个交易日出名单，这个月（20个交易日）内按不同买法进场，看进场后60个交易日相对"全部样本等权、同一天起算"的超额。
  A 月初直接买（收盘）
  B 等回踩：收盘 ≤ 20日线，且 50日线比20天前高、收盘仍在50日线上（上升趋势里的回踩）；当月没出现就不买
  C 等突破：收盘创20日新高；当月没出现就不买
  D 分两次：月初买一半，回踩再买一半（没回踩，第20天买另一半）
另看卖法（从月初买入算，最多拿120天）：
  S1 固定拿60天； S2 跌破50日线卖； S3 从最高点回撤15%卖； S4 纳指跌破200日线卖
只用纳指(QQQ) 200日线上方的月份（规则本来只在牛市用）。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load
import numpy as np, pandas as pd
from us_growth_lib import build_growth

START = "2021-06-01"
g = build_growth()
px = load.us_daily(sorted(set(g.ticker)) + ["QQQ"], start="2019-06-01")
P = px.pivot(index="date", columns="ticker", values="adj_close").sort_index()
qqq = P["QQQ"]; bull = (qqq > qqq.rolling(200).mean()).shift(1)
P = P.drop(columns="QQQ")
days = P.index
MA20 = P.rolling(20).mean(); MA50 = P.rolling(50).mean(); HI20 = P.rolling(20).max().shift(1)
months = [d for d in pd.Series(days, index=days).groupby([days.year, days.month]).first() if d >= pd.Timestamp(START)]
H = 60
EW = P.pct_change().mean(axis=1).fillna(0).add(1).cumprod()          # 样本等权指数（每天再平衡）
Pa = P.to_numpy(); ew = EW.to_numpy(); m20 = MA20.to_numpy(); m50 = MA50.to_numpy(); h20 = HI20.to_numpy()
qa = qqq.reindex(days).to_numpy(); qma = qqq.rolling(200).mean().reindex(days).to_numpy()
cols = list(P.columns)


def fwd(j, i0, h=H):
    if i0 + h >= len(days) or not np.isfinite(Pa[i0, j]) or not np.isfinite(Pa[i0 + h, j]):
        return np.nan
    return (Pa[i0 + h, j] / Pa[i0, j] - 1) - (ew[i0 + h] / ew[i0] - 1)


recs, exits = [], []
for d in months:
    i = days.get_loc(d)
    if i + 20 + H >= len(days) or not bool(bull.loc[d]):
        continue
    snap = g[(g.filed < d) & (g.end > d - pd.Timedelta(days=200))].sort_values("end").groupby(["ticker", "kind"]).last()
    rev = snap.xs("rev", level="kind"); ni = snap.xs("ni", level="kind")
    uni = [t for t in rev.index if t in P.columns and np.isfinite(P.iloc[i][t]) and i >= 120 and np.isfinite(P.iloc[i - 120][t])]
    if len(uni) < 30:
        continue
    r = rev.loc[uni].yoy; n = ni.reindex(uni).yoy
    mom = (P.iloc[i][uni] / P.iloc[i - 120][uni] - 1)
    pick = [t for t in uni if r[t] >= r.quantile(.7) and np.isfinite(n[t]) and n[t] >= n.quantile(.7) and mom[t] > mom.quantile(.3)]
    for t in pick:
        j = cols.index(t)
        rec = {"d": d, "t": t, "A": fwd(j, i)}
        ib = next((k for k in range(i, i + 20) if Pa[k, j] <= m20[k, j] and m50[k, j] > m50[k - 20, j] and Pa[k, j] > m50[k, j]), None)
        ic = next((k for k in range(i, i + 20) if Pa[k, j] > h20[k, j]), None)
        rec["B"] = fwd(j, ib) if ib is not None else np.nan
        rec["C"] = fwd(j, ic) if ic is not None else np.nan
        # D：一半月初、一半回踩（没有就第20天）；以月初为起点的同一60天窗口末端结算，便于和 A 比
        k2 = ib if ib is not None else i + 19
        end = i + H
        rd1 = Pa[end, j] / Pa[i, j] - 1; rd2 = Pa[end, j] / Pa[k2, j] - 1
        rec["D"] = 0.5 * rd1 + 0.5 * rd2 - (0.5 * (ew[end] / ew[i] - 1) + 0.5 * (ew[end] / ew[k2] - 1))
        rec["A_same"] = (Pa[end, j] / Pa[i, j] - 1) - (ew[end] / ew[i] - 1)
        rec["B_wait"] = (k2 - i) if ib is not None else None
        recs.append(rec)
        # 卖法（月初买，最多120天）
        e = {"d": d, "t": t}
        last = min(i + 120, len(days) - 1)
        for name in ["S1", "S2", "S3", "S4"]:
            k_out = i + H if name == "S1" else last
            peak = Pa[i, j]
            for k in range(i + 1, last + 1):
                if not np.isfinite(Pa[k, j]):
                    continue
                peak = max(peak, Pa[k, j])
                if name == "S1" and k == i + H:
                    k_out = k; break
                if name == "S2" and Pa[k, j] < m50[k, j]:
                    k_out = k; break
                if name == "S3" and Pa[k, j] <= peak * 0.85:
                    k_out = k; break
                if name == "S4" and qa[k] < qma[k]:
                    k_out = k; break
            e[name] = (Pa[k_out, j] / Pa[i, j] - 1) - (ew[k_out] / ew[i] - 1)
            e[name + "_days"] = k_out - i
            e[name + "_abs"] = Pa[k_out, j] / Pa[i, j] - 1
        exits.append(e)

R = pd.DataFrame(recs); E = pd.DataFrame(exits)
mid = sorted(R.d.unique())[len(R.d.unique()) // 2]
print(f"牛市月份 {R.d.nunique()}，名单股次 {len(R)}（平均每月 {len(R)/R.d.nunique():.1f} 只），分段点 {pd.Timestamp(mid).date()}")
for c, lab in [("A", "月初直接买"), ("B", "等回踩20日线"), ("C", "等创20日新高"), ("D", "一半月初+一半回踩"), ("A_same", "月初买(同窗口)")]:
    x = R.dropna(subset=[c])
    bym = x.groupby("d")[c].mean()
    h1, h2 = x[x.d < mid][c].mean(), x[x.d >= mid][c].mean()
    print(f"{lab:12s} 触发 {len(x)/len(R):5.0%}  60天超额 {x[c].mean()*100:+.2f}%  胜率 {(x[c]>0).mean():.0%}  月份跑赢 {(bym>0).sum()}/{len(bym)}  前后 {h1*100:+.2f}/{h2*100:+.2f}")
# 只在回踩触发的那些股票上比较：同一批，月初买 vs 等回踩
x = R.dropna(subset=["B"])
print(f"\n同一批（出现回踩的 {len(x)} 次）：月初买 {x.A.mean()*100:+.2f}%  等回踩 {x.B.mean()*100:+.2f}%  平均等 {x.B_wait.mean():.1f} 天")
y = R[R.B.isna()]
print(f"没出现回踩的 {len(y)} 次：月初买 {y.A.mean()*100:+.2f}%")
print("\n== 卖法（月初买入，超额 / 绝对 / 平均拿几天）==")
for s, lab in [("S1", "固定拿60天"), ("S2", "跌破50日线卖"), ("S3", "最高点回撤15%卖"), ("S4", "纳指跌破200日线卖")]:
    h1, h2 = E[E.d < mid][s].mean(), E[E.d >= mid][s].mean()
    print(f"{lab:14s} 超额 {E[s].mean()*100:+.2f}%  绝对 {E[s+'_abs'].mean()*100:+.2f}%  最差10% {E[s+'_abs'].quantile(.1)*100:+.1f}%  拿 {E[s+'_days'].mean():.0f} 天  前后 {h1*100:+.2f}/{h2*100:+.2f}")
R.to_pickle("/home/claude/bt/_us_entry_R.pkl"); E.to_pickle("/home/claude/bt/_us_entry_E.pkl")
