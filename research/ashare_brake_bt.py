"""均线刹车：指数在N日线上才拿（研究 2026-11-14）。小市值组合按天回测和刹车见 ashare_brake_small.py。"""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load
import apanel
P = apanel.build(extra=True); dates = pd.to_datetime(P["dates"])
traded = (np.nan_to_num(P["tradestatus"]) == 1) & np.isfinite(P["close"]) & (np.nan_to_num(P["amount"]) > 0)
st = np.nan_to_num(P["isST"]).astype(bool); age = np.cumsum(traded, axis=0); ok = traded & ~st & (age >= 60)
ewr = pd.Series(np.nanmean(np.where(ok, P["pctChg"] / 100, np.nan), 1), index=dates).fillna(0)
ix = load.a_share_index(start="2015-01-01")
S = {"全A等权": (1 + ewr).cumprod()}
for c, n in [("sh.000300", "沪深300"), ("sh.000905", "中证500"), ("sh.000852", "中证1000")]:
    S[n] = ix[ix.code == c].set_index("date").close.sort_index()
def ann(x): return (1 + x).prod() ** (250 / len(x)) - 1 if len(x) else np.nan
def mdd(x): e = (1 + x).cumprod(); return (e / e.cummax() - 1).min()
rows = []
for n, px in S.items():
    r = px.pct_change()
    for w in (0, 10, 20, 60, 120):
        if w == 0:
            sig = pd.Series(True, index=px.index)
        else:
            sig = (px > px.rolling(w).mean()).shift(1).fillna(False)
        sw = (sig != sig.shift()).astype(float)
        x = (r.where(sig, 0.0) - sw * 0.0005).dropna()
        row = {"指数": n, "均线": w or "一直拿"}
        for lab, a, b in [("近5年", "2021-11-01", None), ("前半", "2021-11-01", "2024-05-14"), ("后半", "2024-05-15", None), ("2016-21", "2016-01-01", "2021-10-31")]:
            y = x[a:b]; row[lab] = f"{ann(y)*100:+.1f}%"
            if lab in ("近5年", "2016-21"): row[lab + "回撤"] = f"{mdd(y)*100:.0f}%"
        row["每年换几次"] = round(sw["2021-11-01":].sum() / 5, 0)
        rows.append(row)
pd.set_option("display.width", 250); print(pd.DataFrame(rows).to_string(index=False))


# ---------------- 小市值30只组合（按天）+ 刹车
