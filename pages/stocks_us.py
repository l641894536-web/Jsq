"""美股正股名单（页面"正股"页用，写 stocks_us.json）。
规则（回测 research/us_growth_bt.py、research/us_entry_bt.py）：
  范围 = 币安上线过合约、有SEC财报的美股（约150只）；只用公告日之后的数。
  名单 = 最近一季 营收同比、净利润同比 都在范围前30%，近120个交易日涨跌不在最弱30%，
         而且离一年高点不到30%（跌了30%以上的高成长股之后60天反而跑输，research/us_entry_bt.py）。
  观察 = 成长够了，但跌太多/太弱：等它回到一年高点的70%以上（need = 0.7×一年高点）。
  只在纳指100站上200日线时新买；名单出来直接买（等回踩/等新高不更好），单只不设均线止损；
  纳指跌破200日线停止新买，跌到认错线全卖。
用法：被 env_pipeline.py 调用 build(fund_dir, out_path, load, us_state)；也可单独跑：
  python3 stocks_us.py --fund fund --data data --out stocks_us.json
"""
import json, os
import numpy as np
import pandas as pd

REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax"]


def _quarters(g):
    q = g[(g.days >= 80) & (g.days <= 100)][["end", "val", "filed"]].copy()
    have = set(q.end)
    rows = []
    for _, r in g[g.days > 100].iterrows():
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


def growth_table(fund):
    f = pd.read_csv(f"{fund}/us/financials.csv.xz", parse_dates=["start", "end", "filed"])
    f = f[f.unit == "USD"]
    f["days"] = (f.end - f.start).dt.days
    f["kind"] = np.where(f.concept.isin(REV), "rev", np.where(f.concept == "NetIncomeLoss", "ni", ""))
    f = f[f.kind != ""]
    f = f.sort_values("filed").groupby(["ticker", "kind", "start", "end"], as_index=False).first()
    recs = []
    for (tk, kind), g in f.groupby(["ticker", "kind"]):
        q = _quarters(g).reset_index(drop=True)
        for _, r in q.iterrows():
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
    return pd.DataFrame(recs)


def build(fund, out, load, us_state=None):
    g = growth_table(fund)
    tks = sorted(set(g.ticker))
    px = load.us_daily(tks, start=str((pd.Timestamp.today() - pd.Timedelta(days=500)).date()))
    P = px.pivot(index="date", columns="ticker", values="adj_close").sort_index().ffill(limit=3)
    C = px.pivot(index="date", columns="ticker", values="close").sort_index().ffill(limit=3)
    d = P.index[-1]
    snap = g[(g.filed <= d) & (g.end > d - pd.Timedelta(days=200))].sort_values("end").groupby(["ticker", "kind"]).last()
    rev = snap.xs("rev", level="kind")
    ni = snap.xs("ni", level="kind")
    i = len(P) - 1
    uni = [t for t in rev.index if t in P.columns and np.isfinite(P.iloc[i][t]) and i >= 120 and np.isfinite(P.iloc[i - 120][t])]
    r = rev.loc[uni].yoy
    n = ni.reindex(uni).yoy
    mom = P.iloc[i][uni] / P.iloc[i - 120][uni] - 1
    rq = lambda s: s.rank(pct=True)
    r_r, n_r, m_r = rq(r), rq(n), rq(mom)
    ma50 = C.rolling(50).mean().iloc[i]
    ma200 = C.rolling(200, min_periods=150).mean().iloc[i]
    hi252 = C.rolling(252, min_periods=150).max().iloc[i]
    dd = (C.iloc[i][uni] / hi252[uni] - 1).fillna(0)
    grow = (r >= r.quantile(.7)) & (n >= n.quantile(.7))
    pick = grow & (mom > mom.quantile(.3)) & (dd > -0.3)
    watch = grow & ~pick
    meta = load.us_universe().set_index("ticker")
    nm = meta.name.to_dict() if "name" in meta else {}
    sec = meta.sector.to_dict() if "sector" in meta else {}
    rows = []
    for t in uni:
        c = C.iloc[i][t]
        f2 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 3)
        rows.append([t, nm.get(t) or "", sec.get(t) or "", f2(r[t]), f2(n.get(t, np.nan)), f2(r_r[t]), f2(n_r.get(t, np.nan)),
                     f2(mom[t]), f2(m_r[t]), f2(c), f2(c / ma50[t] - 1), f2(c / ma200[t] - 1) if np.isfinite(ma200[t]) else None,
                     f2(c / hi252[t] - 1) if np.isfinite(hi252[t]) else None, f2(0.7 * hi252[t]), str(rev.loc[t].end.date()), str(rev.loc[t].filed.date()),
                     2 if pick[t] else (1 if watch[t] else 0)])
    rows.sort(key=lambda x: (-x[-1], -(x[5] or 0) - (x[6] or 0)))
    o = dict(date=str(d.date()), us_state=us_state, n_uni=len(uni), n_pick=int(pick.sum()), n_watch=int(watch.sum()),
             cut=dict(rev=round(float(r.quantile(.7)), 3), ni=round(float(n.quantile(.7)), 3), mom=round(float(mom.quantile(.3)), 3)),
             fields=["t", "name", "sector", "rev", "ni", "rev_r", "ni_r", "mom120", "m_r", "px", "vs50", "vs200", "dd52", "need", "q_end", "filed", "pick"],
             rows=rows)
    json.dump(o, open(out, "w"), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return dict(date=o["date"], n_uni=o["n_uni"], n_pick=o["n_pick"], picks=[x[0] for x in rows if x[-1] == 2], watch=[x[0] for x in rows if x[-1] == 1])


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", required=True); ap.add_argument("--data", required=True)
    ap.add_argument("--jsq", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--out", default="stocks_us.json")
    a = ap.parse_args()
    os.environ["MARKET_DATA"] = a.data
    sys.path.insert(0, a.jsq)
    from market_data import load as _load
    print(build(a.fund, a.out, _load))
