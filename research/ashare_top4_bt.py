"""【已被 ashare_top5_bt.py 取代：本脚本原先卖半时把股数写死为0.5（已修正），且按当天收盘成交；结论以 top5 为准】
'涨过头卖一半'（比60日线高40%卖一半、回到60日线买回）该不该分情况：在第一次触发那天看
  ①位置：现价 ÷ 之前2.5年（不含最近120天）最高价——回到老高附近(≤1.2倍) / 冲出一些(1.2~1.5) / 冲出很远(>1.5)，没有2.5年历史的算"次新"
  ②业绩：最近已公告的归母净利润同比（YOYPNI）——≥30% / 0~30% / 下滑；以及是否比上一期加速
  ③速度：从120天低点涨了多少
看每组里"卖一半"比"一直拿着"多赚多少（250天到期），以及触发后120天它比大盘多涨多少。前后两段 + 2016~2021 复核。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct, MID
from ashare_top_bt import find, H, COST


def gr_table():
    g = pd.read_csv("/home/claude/fund/a_share/growth.csv.xz", dtype={"code": str}, parse_dates=["pubDate", "statDate"])
    g = g[g.pubDate.notna()].sort_values(["code", "statDate"])
    g["prev"] = g.groupby("code").YOYPNI.shift(1)
    g = g.sort_values("pubDate")
    return {c: (x.pubDate.to_numpy(), x.YOYPNI.to_numpy(float), x.prev.to_numpy(float)) for c, x in g.groupby("code")}


def run(W, R, lab):
    adj = W["adj"]; codes = W["codes"]; dates = W["dates"]
    ma60 = pd.DataFrame(adj).rolling(60, min_periods=45).mean().to_numpy()
    ew = W["ref"]["全A等权"]; GT = gr_table()
    rows = []
    for i, j in zip(R.i, R.j):
        c = adj[:, j]; end = i + H
        u, cash, full, t1 = 1.0, 0.0, True, None
        for t in range(i + 1, end + 1):
            x = c[t]
            if not np.isfinite(x): continue
            if full and x >= 1.4 * ma60[t, j]:
                q = u / 2; cash = q * x * (1 - COST); u -= q; full = False; t1 = t1 if t1 is not None else t   # 2026-11-14 修正：原来写死 u = 0.5，买回后股数≠1 时记错
            elif not full and x <= ma60[t, j]:
                u += cash / x * (1 - COST); cash = 0; full = True
        hold = c[end] / c[i] - 1; rule = (u * c[end] + cash) / c[i] - 1
        r = dict(i=i, j=j, d=dates[i], hold=hold, rule=rule, trig=t1 is not None, ind=W["ind"][j])
        if t1 is not None:
            past = c[max(0, t1 - 750):t1 - 120]
            r["pos"] = c[t1] / np.nanmax(past) if np.isfinite(past).sum() >= 400 else np.nan
            r["rise"] = c[t1] / np.nanmin(c[t1 - 120:t1]) - 1
            v = GT.get(codes[j])
            if v is not None:
                k = np.searchsorted(v[0], np.datetime64(dates[t1]), side="right") - 1
                r["gr"] = v[1][k] if k >= 0 else np.nan; r["gacc"] = (v[1][k] > v[2][k]) if k >= 0 and np.isfinite(v[2][k]) else np.nan
            e2 = min(t1 + 120, len(c) - 1)
            r["f120"] = (c[e2] / c[t1] - 1) - (ew[e2] / ew[t1] - 1)
            r["mdd120"] = np.nanmin(c[t1:e2 + 1]) / c[t1] - 1
        rows.append(r)
    D = pd.DataFrame(rows); D["per"] = np.where(D.d < MID, "前半", "后半"); D["diff"] = D.rule - D.hold
    T = D[D.trig].copy()
    print(f"\n######## {lab}：{len(D):,} 次大涨后创新高，其中 {len(T):,} 次之后涨到比60日线高40%（触发卖一半）；全部：卖一半比拿着 {pct(D['diff'].mean())}")
    groups = [("回到老高附近(≤1.2倍)", T.pos <= 1.2), ("冲出一些(1.2~1.5倍)", (T.pos > 1.2) & (T.pos <= 1.5)), ("冲出很远(>1.5倍)", T.pos > 1.5), ("次新(没2.5年历史)", T.pos.isna()),
              ("业绩同比≥30%", T.gr >= 0.3), ("业绩0~30%", (T.gr >= 0) & (T.gr < 0.3)), ("业绩下滑", T.gr < 0),
              ("业绩在加速", T.gacc == True), ("业绩在减速", T.gacc == False),
              ("从低点涨<80%", T.rise < 0.8), ("从低点涨80~150%", (T.rise >= 0.8) & (T.rise < 1.5)), ("从低点涨≥150%", T.rise >= 1.5),
              ("老高附近+业绩≥30%", (T.pos <= 1.2) & (T.gr >= 0.3)), ("冲出很远+业绩≥30%", (T.pos > 1.5) & (T.gr >= 0.3)), ("冲出很远+业绩<30%", (T.pos > 1.5) & (T.gr < 0.3))]
    out = []
    for nm, m in groups:
        x = T[m.fillna(False).astype(bool)]
        if len(x) < 40: continue
        row = {"触发那天": nm, "次数": len(x), "卖一半比拿着": pct(x["diff"].mean()), "卖了更好": f"{(x['diff'] > 0.001).mean():.0%}",
               "之后120天比大盘": pct(x.f120.mean()), "之后120天最深跌": pct(x.mdd120.median())}
        for p in ["前半", "后半"]:
            y = x[x.per == p]
            if len(y) >= 20: row[p] = pct(y["diff"].mean())
        row["电子"] = pct(x[x.ind == "C39"]["diff"].mean()) if (x.ind == "C39").sum() >= 20 else "—"
        out.append(row)
    print(pd.DataFrame(out).to_string(index=False))
    return D


if __name__ == "__main__":
    if os.environ.get("WHICH", "main") == "main":
        W = world("2015-01-01"); D = run(W, find(W, pd.Timestamp("2021-11-01"), pd.Timestamp("2025-10-31")), "近5年")
    else:
        W = world("2015-01-01"); D = run(W, find(W, pd.Timestamp("2016-07-01"), pd.Timestamp("2021-10-31")), "复核 2016-07→2021-10")
    D.to_pickle(f"/tmp/_top4_{os.environ.get('WHICH', 'main')}.pkl")
