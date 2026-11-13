"""小市值30只组合按天的收益和最大回撤，以及加"全A等权跌破20日线清仓"刹车（研究 2026-11-14）。"""
import numpy as np, pandas as pd
import os; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ashare_small_bt.py")).read().split("W5 = per != \"2016-21\"")[0])
import apanel
P = apanel.build(extra=True); dates = pd.to_datetime(P["dates"]); T = len(dates)
traded = (np.nan_to_num(P["tradestatus"]) == 1) & np.isfinite(P["close"]) & (np.nan_to_num(P["amount"]) > 0)
pct = np.where(traded, P["pctChg"] / 100, 0.0)
st = np.nan_to_num(P["isST"]).astype(bool); age = np.cumsum(traded, axis=0); ok = traded & ~st & (age >= 60)
ewr = pd.Series(np.nanmean(np.where(ok, P["pctChg"] / 100, np.nan), 1), index=dates).fillna(0)
day = pd.Series(np.nan, index=dates)
for k in range(len(R)):
    idx = basket(k, 30); i0 = R[k]; i1 = min(R[k] + 19, T - 1); i_next = R[k + 1] if k + 1 < len(R) else T
    first = np.nanmean(P["close"][i0, idx] / P["open"][i0, idx] - 1)
    day.iloc[i0] = first - 0.0025
    for t in range(i0 + 1, min(i_next, T)):
        day.iloc[t] = np.nanmean(pct[t, idx])        # 一直拿到下次换仓（回测里第20天后空几天，这里接着拿）
day = day.dropna()
ewi = (1 + ewr).cumprod()
def ann(x): return (1 + x).prod() ** (250 / len(x)) - 1
def mdd(x): e = (1 + x).cumprod(); return (e / e.cummax() - 1).min()
for w in (0, 20, 60):
    if w:
        sig = (ewi > ewi.rolling(w).mean()).shift(1).reindex(day.index).fillna(False)
        sw = (sig != sig.shift()).astype(float)
        x = day.where(sig, 0.0) - sw * 0.003
    else:
        x = day
    out = {lab: f"{ann(x[a:b])*100:+.1f}%/{mdd(x[a:b])*100:.0f}%" for lab, a, b in [("近5年", "2021-11-01", None), ("前半", "2021-11-01", "2024-05-14"), ("后半", "2024-05-15", None), ("2016-21", "2016-02-01", "2021-10-31")]}
    print("小市值30", "一直拿" if not w else f"全A等权在{w}日线上才拿", out)
# 每周五看一次
fri = ewi.index.dayofweek == 4
for w in (20,):
    raw = (ewi > ewi.rolling(w).mean())
    wk = raw.where(fri).ffill().shift(1).reindex(day.index).fillna(False).astype(bool)
    sw = (wk != wk.shift()).astype(float)
    x = day.where(wk, 0.0) - sw * 0.003
    out = {lab: f"{ann(x[a:b])*100:+.1f}%/{mdd(x[a:b])*100:.0f}%" for lab, a, b in [("近5年", "2021-11-01", None), ("前半", "2021-11-01", "2024-05-14"), ("后半", "2024-05-15", None), ("2016-21", "2016-02-01", "2021-10-31")]}
    print("小市值30 每周五看全A等权20日线", out, "每年换", round(sw["2021-11-01":].sum() / 5))
    sig = raw.shift(1).reindex(day.index).fillna(False); print("每天看 每年换", round((sig != sig.shift()).astype(float)["2021-11-01":].sum() / 5))
    print("现在全A等权 vs 20日线:", round(float(ewi.iloc[-1] / ewi.rolling(20).mean().iloc[-1] - 1) * 100, 2), "%", ewi.index[-1].date())
e = (1 + day).cumprod(); dd = e / e.cummax() - 1
x = dd["2021-11-01":]; t1 = x.idxmin(); pk = e[:t1].idxmax()
print("近5年最大回撤", round(x.min()*100,1), "从", pk.date(), "到", t1.date())
for y in range(2016, 2027):
    z = day[str(y)]; ez = (1 + z).cumprod(); print(y, f"全年 {((1+z).prod()-1)*100:+.1f}% 年内最大回撤 {((ez/ez.cummax()-1).min())*100:.0f}%")
sig = (ewi > ewi.rolling(20).mean()).shift(1).reindex(day.index).fillna(False); sw = (sig != sig.shift()).astype(float)
xs = day.where(sig, 0.0) - sw * 0.003
for y in range(2021, 2027):
    z = xs[str(y)]; ez = (1 + z).cumprod(); print(y, "带刹车", f"{((1+z).prod()-1)*100:+.1f}% 回撤 {((ez/ez.cummax()-1).min())*100:.0f}%")
