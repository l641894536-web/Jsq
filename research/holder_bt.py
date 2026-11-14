"""深跌持仓怎么处理 / 想抄底什么时候买（A股、美股，近5年）
起点：一只股票第一次跌到一年高点的70%以下（之前60天里还在75%以上，避免一直触发）= 你被套了30%左右。
之后250个交易日内：
  L = 起点之后的最低收盘；第一波反弹 E1 = 第一次从当时的最低点涨回15%；
  二次确认 E2 = E1 之后从反弹高点回落≥8% 但没破 L，然后收盘再过反弹高点。
持有人（起点时手里1份）的做法，看250天后：
  死扛：一直拿
  反弹卖一半：E1 卖一半，E2 出现再买回这一半
  反弹全卖：E1 全卖，E2 出现再全买回
  越跌越加：比起点再跌10%、20%各加1份，一直拿（按投入的总钱算收益）
想买的人（手里是现金）：起点就买 / E1 买 / E2 买，都拿到起点后250天；以及买完60天内再跌10%的比例。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
from rally_dip_bt import panel_a, panel_us   # noqa（会先跑一遍 rally_dip 的打印，忽略）

H = 250
START, MID = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-15")


def run(dates, adjf, U, ew, lab):
    T, N = adjf.shape
    hi250 = pd.DataFrame(adjf).rolling(250, min_periods=200).max().to_numpy()
    ewi = (1 + ew).cumprod().to_numpy()
    rows = []
    t0 = dates.searchsorted(START)
    for j in range(N):
        c = adjf[:, j]
        ratio = c / hi250[:, j]
        i = max(t0, 260); last = -999
        while i < T - H:
            if U[i, j] and ratio[i] <= 0.70 and np.nanmax(ratio[i - 60:i]) >= 0.75 and i - last > 60:
                last = i
                p0 = c[i]; end = i + H
                L = p0; E1 = E2 = None; P = None; pulled = False
                for t in range(i + 1, end + 1):
                    x = c[t]
                    if not np.isfinite(x):
                        continue
                    if E1 is None:
                        L = min(L, x)
                        if x >= L * 1.15:
                            E1 = t; P = x
                    elif E2 is None:
                        if x < L:            # 破了前低：这一轮反弹失败，之后不再算二次确认（只用当时能知道的第一波反弹）
                            E2 = -1; continue
                        if not pulled:
                            if x > P: P = x
                            elif x <= P * 0.92: pulled = True
                        elif x > P:
                            E2 = t
                if E2 == -1: E2 = None
                cE = c[end]
                hold = cE / p0 - 1
                # 反弹卖一半/全卖
                def sellback(frac):
                    if E1 is None:
                        return hold
                    cash = frac * c[E1] / p0                         # 卖掉部分换成的钱（以起点1份=1）
                    keep = (1 - frac) * cE / p0
                    if E2 is not None:
                        back = cash / c[E2] * cE                     # 用卖的钱在 E2 买回
                        return keep + back - 1
                    return keep + cash - 1
                # 越跌越加
                units, cost = 1.0, p0
                for lvl in (0.9, 0.8):
                    hit = np.where(c[i + 1:end + 1] <= p0 * lvl)[0]
                    if len(hit):
                        units += 1; cost += c[i + 1 + hit[0]]
                avg_dn = units * cE / cost - 1
                # 最大浮亏（死扛）
                mdd = np.nanmin(c[i:end + 1]) / p0 - 1
                r = dict(d=dates[i], i=i, j=j, hold=hold, half=sellback(0.5), full=sellback(1.0), avgdn=avg_dn, units=units, mdd=mdd,
                         e1=E1 is not None, e2=E2 is not None, out1=(c[E1]/p0-1) if E1 is not None else hold, mkt=ewi[end] / ewi[i] - 1)
                # 想买的人
                for nm, k in [("buy0", i), ("buy1", E1), ("buy2", E2)]:
                    if k is None:
                        r[nm] = np.nan; r[nm + "_dd"] = np.nan; continue
                    r[nm] = cE / c[k] - 1
                    w = c[k + 1:min(k + 61, T)]
                    r[nm + "_dd"] = np.nanmin(w) < c[k] * 0.9 if len(w) else np.nan
                rows.append(r)
                i += 60
            else:
                i += 1
    R = pd.DataFrame(rows)
    R["per"] = np.where(R.d < MID, "前半", "后半")
    pct = lambda v: f"{v*100:+.1f}%"
    print(f"\n######## {lab}：{len(R):,} 次'被套30%'（起点 {R.d.min().date()}→{R.d.max().date()}），250天后（同期大盘 {pct(R.mkt.mean())}）")
    print(f"出现第一波反弹 {R.e1.mean():.0%}，出现二次确认 {R.e2.mean():.0%}；死扛期间最低平均再跌 {pct(R.mdd.mean())}，再跌20%以上的 {(R.mdd<=-0.2).mean():.0%}")
    out = []
    for nm, col in [("死扛", "hold"), ("反弹卖一半、确认再买回", "half"), ("反弹全卖、确认再买回", "full"), ("越跌越加(跌10%/20%各加1份)", "avgdn")]:
        x = R[col]
        out.append({"做法": nm, "250天后平均": pct(x.mean()), "中位数": pct(x.median()), "最差10%": pct(x.quantile(.1)), "亏钱的比例": f"{(x<0).mean():.0%}",
                    "前半": pct(x[R.per == '前半'].mean()), "后半": pct(x[R.per == '后半'].mean())})
    print(pd.DataFrame(out).to_string(index=False))
    out = []
    for nm, col in [("跌30%就买（抄底）", "buy0"), ("第一波反弹（从低点涨15%）买", "buy1"), ("二次确认后买", "buy2")]:
        x = R[col].dropna(); dd = R[col + "_dd"].dropna().astype(bool)
        out.append({"买法": nm, "有机会买的比例": f"{R[col].notna().mean():.0%}", "买后到期平均": pct(x.mean()), "中位数": pct(x.median()), "亏钱的比例": f"{(x<0).mean():.0%}",
                    "买完60天内再跌10%": f"{dd.mean():.0%}", "前半": pct(x[R.loc[x.index, 'per'] == '前半'].mean()), "后半": pct(x[R.loc[x.index, 'per'] == '后半'].mean())})
    print(pd.DataFrame(out).to_string(index=False))
    return R


if __name__ == "__main__":
    RA = run(*panel_a(), "A股")
    RU = run(*panel_us(), "美股")
    pd.to_pickle({"A": RA, "US": RU}, "/home/claude/bt/_holder.pkl")
