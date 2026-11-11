"""美股成长选股回测：营收/净利润同比增速、是否加快 × 纳指(QQQ)200日线牛熊。
只用公告日(filed)之后的数据；每月第一个交易日选股，看之后20/60个交易日相对"全部样本等权"的超额。
样本 = 币安上线过的美股（约160只，偏热门股，有选择偏差）。
用法: python3 us_growth_bt.py [--fund /home/claude/fund] [--start 2021-06-01]
"""
import sys, argparse
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

ap = argparse.ArgumentParser()
ap.add_argument("--fund", default="/home/claude/fund")
ap.add_argument("--start", default="2021-06-01")
ap.add_argument("--out", default="us_growth_report.csv")
a = ap.parse_args()

REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax"]
f = pd.read_csv(f"{a.fund}/us/financials.csv.xz", parse_dates=["start", "end", "filed"])
f = f[f.unit == "USD"]
f["days"] = (f.end - f.start).dt.days
f["kind"] = np.where(f.concept.isin(REV), "rev", np.where(f.concept == "NetIncomeLoss", "ni", ""))
f = f[f.kind != ""]
# 每个 (股票, 指标, 起, 止) 取最早公告日 = 市场第一次看到这个数的日子
f = f.sort_values("filed").groupby(["ticker", "kind", "start", "end"], as_index=False).first()


def quarters(g):
    """单季值：直接披露的季度 + 用累计值相减补出的季度（公告日取被减数的公告日）。"""
    q = g[(g.days >= 80) & (g.days <= 100)][["end", "val", "filed"]].copy()
    have = set(q.end)
    cum = g[g.days > 100]
    rows = []
    for _, r in cum.iterrows():
        if r.end in have:
            continue
        prev = g[(g.start == r.start) & (g.end < r.end) & ((r.end - g.end).dt.days.between(80, 100))]
        if len(prev):
            p = prev.sort_values("days").iloc[-1]
            rows.append({"end": r.end, "val": r.val - p.val, "filed": max(r.filed, p.filed)})
            have.add(r.end)
    if rows:
        q = pd.concat([q, pd.DataFrame(rows)])
    return q.sort_values("filed").drop_duplicates("end").sort_values("end")


recs = []
for (tk, kind), g in f.groupby(["ticker", "kind"]):
    q = quarters(g).reset_index(drop=True)
    for i, r in q.iterrows():
        py = q[(q.end - (r.end - pd.Timedelta(days=365))).abs() <= pd.Timedelta(days=20)]
        if not len(py):
            continue
        b = py.iloc[0].val
        if kind == "rev":
            if b <= 0:
                continue
            yoy = r.val / b - 1
        else:
            if b == 0:
                continue
            yoy = (r.val - b) / abs(b)
        recs.append({"ticker": tk, "kind": kind, "end": r.end, "filed": r.filed, "yoy": yoy})
g = pd.DataFrame(recs)
g = g.sort_values(["ticker", "kind", "end"])
g["prev"] = g.groupby(["ticker", "kind"]).yoy.shift(1)
g["acc"] = g.yoy > g.prev
print("有同比的季度数:", g.groupby("kind").size().to_dict(), "股票数:", g.ticker.nunique(), "最早公告:", g.filed.min().date())

px = load.us_daily(sorted(set(g.ticker)) + ["QQQ"], start="2019-06-01")
P = px.pivot(index="date", columns="ticker", values="adj_close").sort_index()
qqq = P["QQQ"]; bull = (qqq > qqq.rolling(200).mean()).shift(1)
P = P.drop(columns="QQQ")
days = P.index
months = [d for d in pd.Series(days, index=days).groupby([days.year, days.month]).first() if d >= pd.Timestamp(a.start)]

out = []
for d in months:
    i = days.get_loc(d)
    snap = g[(g.filed < d) & (g.end > d - pd.Timedelta(days=200))].sort_values("end").groupby(["ticker", "kind"]).last()
    rev = snap.xs("rev", level="kind") if "rev" in snap.index.get_level_values("kind") else pd.DataFrame()
    ni = snap.xs("ni", level="kind") if "ni" in snap.index.get_level_values("kind") else pd.DataFrame()
    for h in (20, 60):
        if i + h >= len(days):
            continue
        fwd = (P.iloc[i + h] / P.iloc[i] - 1).dropna()
        mom = (P.iloc[i] / P.iloc[i - 120] - 1).dropna() if i >= 120 else pd.Series(dtype=float)
        uni = fwd.index.intersection(rev.index)
        if len(uni) < 30:
            continue
        base = fwd[uni].mean()
        r = rev.loc[uni]; hi = r.yoy >= r.yoy.quantile(0.7); lo = r.yoy <= r.yoy.quantile(0.3)
        n2 = ni.reindex(uni); nhi = n2.yoy >= n2.yoy.quantile(0.7)
        m = mom.reindex(uni); weak = m <= m.quantile(0.3); strong = m >= m.quantile(0.7)
        groups = {"营收增速前30%": hi, "营收增速前30%且加快": hi & r.acc, "营收增速后30%": lo,
                  "净利增速前30%": nhi, "净利增速前30%且加快": nhi & n2.acc.fillna(False).astype(bool),
                  "营收净利都前30%": hi & nhi, "高成长+近半年强": hi & strong, "高成长+近半年弱": hi & weak,
                  "近半年最强30%": strong, "近半年最弱30%": weak}
        for name, mask in groups.items():
            s = fwd[uni][mask.values]
            if len(s) >= 5:
                out.append({"date": d, "h": h, "bull": bool(bull.loc[d]), "grp": name, "n": len(s),
                            "ex": s.mean() - base, "base": base, "qqq": qqq.iloc[i + h] / qqq.iloc[i] - 1})
o = pd.DataFrame(out)
mid = months[len(months) // 2]
rows = []
for (h, grp, b), x in o.groupby(["h", "grp", "bull"]):
    x1, x2 = x[x.date < mid], x[x.date >= mid]
    rows.append({"h": h, "grp": grp, "env": "牛" if b else "熊", "months": len(x), "avg_n": round(x.n.mean()),
                 "ex%": round(x.ex.mean() * 100, 2), "win_months": int((x.ex > 0).sum()),
                 "half1%": round(x1.ex.mean() * 100, 2) if len(x1) else None, "n1": len(x1),
                 "half2%": round(x2.ex.mean() * 100, 2) if len(x2) else None, "n2": len(x2),
                 "t": round(x.ex.mean() / x.ex.std() * np.sqrt(len(x) / (h / 20)), 2) if len(x) > 2 else None})
rep = pd.DataFrame(rows).sort_values(["h", "env", "grp"])
rep.to_csv(a.out, index=False)
pd.set_option("display.width", 250)
print("月份:", len(months), months[0].date(), "→", o.date.max().date(), "分段点:", mid.date())
print(rep.to_string(index=False))
b = o[(o.grp == "营收增速前30%")].groupby(["h", "bull"]).agg(base=("base", "mean"), qqq=("qqq", "mean"), m=("date", "count"))
print("\n样本等权 vs QQQ 平均涨幅:\n", (b * [100, 100, 1]).round(2))
