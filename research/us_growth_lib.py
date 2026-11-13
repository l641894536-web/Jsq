"""美股成长数据：每只股票每季营收/净利润同比（只用公告日之后可见的数）。抽自 research/us_growth_bt.py。"""
import numpy as np, pandas as pd


def build_growth(fund="/home/claude/fund"):
    REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
           "RevenueFromContractWithCustomerIncludingAssessedTax"]
    f = pd.read_csv(f"{fund}/us/financials.csv.xz", parse_dates=["start", "end", "filed"])
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

    return g
