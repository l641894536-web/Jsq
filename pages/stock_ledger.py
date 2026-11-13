"""正股名单自动记账（前向验证，2026-11-14 起）。
每个月第一次跑到这个月的数据时，把当时的名单记下来（按当天收盘价"买入"，等权），之后每天更新到最新收盘，满20个交易日就结账。
  A股小市值30：stocks_a.json 里 sm=1..30（research/ashare_small_bt.py），对照 中证1000、沪深300
  美股成长名单：stocks_us.json 里 pick=2（research/us_entry_bt.py），对照 QQQ
和回测的差别：回测是月初第一个交易日开盘买，这里是"这个月第一次出数据的那天收盘"买，第一个月从中途开始。
用法：python3 stock_ledger.py --data data --jsq code --site site   （在 env_pipeline.py 之后跑）
"""
import argparse, json, os, sys
import numpy as np, pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--jsq", required=True); ap.add_argument("--site", required=True)
a = ap.parse_args()
os.environ["MARKET_DATA"] = a.data
sys.path.insert(0, a.jsq)
from market_data import load  # noqa: E402

OUT = os.path.join(a.site, "stock_ledger.json")
L = json.load(open(OUT)) if os.path.exists(OUT) else {"note": __doc__.strip().splitlines()[0], "baskets": []}
r = lambda x, n=4: None if x is None or not np.isfinite(x) else round(float(x), n)
HOLD = 20


def a_prices(codes, start):
    d = load.a_share(start=start, codes=codes, adjust=None)[["date", "code", "close", "pctChg", "tradestatus"]]
    d = d[d.tradestatus.astype(str) == "1"]
    out = {}
    for c, g in d.groupby("code"):
        g = g.sort_values("date")
        out[c] = pd.Series(np.cumprod(1 + g.pctChg.astype(float).to_numpy() / 100), index=g.date.values), g.close.astype(float).iloc[-1]
    return out


def idx_series(codes, start):
    ix = load.a_share_index(codes=codes, start=start)
    return {c: g.set_index("date").close.sort_index() for c, g in ix.groupby("code")}


def us_prices(tks, start):
    d = load.us_daily(tks, start=start)
    return {t: g.set_index("date").adj_close.sort_index() for t, g in d.groupby("ticker")}


def track(series, d0):
    """d0 收盘买入 → 最新（或满20个交易日）收盘的收益；返回 (收益, 交易日数, 截止日期)"""
    s = series[series.index >= pd.Timestamp(d0)]
    if not len(s):
        return None, 0, None
    k = min(HOLD, len(s) - 1)
    return s.iloc[k] / s.iloc[0] - 1, int(k), str(pd.Timestamp(s.index[k]).date())


# ---------------- 新开一篮（这个月还没记过）
def open_basket(kind, date, members, bench):
    month = date[:7]
    if any(b["kind"] == kind and b["month"] == month for b in L["baskets"]):
        return
    L["baskets"].append(dict(kind=kind, month=month, date=date, members=members, bench=bench, ret=None, days=0, closed=False))
    print("新记一篮", kind, date, len(members), "只")


sa_p = os.path.join(a.site, "stocks_a.json")
if os.path.exists(sa_p):
    sa = json.load(open(sa_p)); F = sa["fields"]
    if "sm" in F:
        rows = [dict(zip(F, x)) for x in sa["rows"]]
        sm = sorted([x for x in rows if 0 < (x.get("sm") or 0) <= 30], key=lambda x: x["sm"])
        if len(sm) == 30:
            open_basket("A股小市值30", sa["date"], [dict(code=("sh." if x["code"].startswith("6") else "sz.") + x["code"], name=x["name"], cap=x["cap"]) for x in sm],
                        ["sh.000852", "sh.000300"])
su_p = os.path.join(a.site, "stocks_us.json")
if os.path.exists(su_p):
    su = json.load(open(su_p)); F = su["fields"]
    rows = [dict(zip(F, x)) for x in su["rows"]]
    pk = [x for x in rows if x.get("pick") == 2]
    if pk:
        open_basket("美股成长名单", su["date"], [dict(code=x["t"], name=x["name"]) for x in pk], ["QQQ"])

# ---------------- 更新没结账的
for b in L["baskets"]:
    if b["closed"]:
        continue
    start = str((pd.Timestamp(b["date"]) - pd.Timedelta(days=5)).date())
    if b["kind"].startswith("A股"):
        P = a_prices([m["code"] for m in b["members"]], start)
        for m in b["members"]:
            s = P.get(m["code"], (None, None))[0]
            m["ret"], m["days"], _ = track(s, b["date"]) if s is not None else (None, 0, None)
        I = idx_series(b["bench"], start)
        bench = {c: track(I[c], b["date"])[0] for c in b["bench"] if c in I}
    else:
        P = us_prices([m["code"] for m in b["members"]] + b["bench"], start)
        for m in b["members"]:
            s = P.get(m["code"])
            m["ret"], m["days"], _ = track(s, b["date"]) if s is not None else (None, 0, None)
        bench = {c: track(P[c], b["date"])[0] for c in b["bench"] if c in P}
    rs = [m["ret"] for m in b["members"] if m.get("ret") is not None]
    b["ret"] = r(np.mean(rs)) if rs else None
    b["days"] = int(max([m.get("days") or 0 for m in b["members"]] + [0]))
    b["bench_ret"] = {k: r(v) for k, v in bench.items()}
    for m in b["members"]:
        m["ret"] = r(m.get("ret"))
    b["closed"] = b["days"] >= HOLD
    print(b["kind"], b["month"], "第", b["days"], "天", "收益", b["ret"], "对照", b["bench_ret"])

L["updated"] = str(pd.Timestamp.now(tz="UTC").floor("min"))
json.dump(L, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
