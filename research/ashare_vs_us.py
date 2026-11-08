"""A股 vs 美股：周期和情绪在哪边更"值钱"？同一时间段（2006-2026），同一套方法。
1) 周期：只在指数站上200日线时持有（否则空仓）vs 一直拿着 —— 看过滤后收益/回撤改善多少。
2) 跌破200日线后的基准概率（同前面美股研究的定义）。
3) 情绪：成交额热度（20日均成交额 / 250日均成交额）分五档，看之后3个月、6个月的涨跌。"""
import sys, os
sys.path.insert(0, "/home/claude/src/Jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import bear

import sys as _s
START, END = (_s.argv[1] if len(_s.argv)>1 else "2006-01-01"), "2026-11-06"
ix = load.a_share_index()
A = {"沪深300": "sh.000300", "上证指数": "sh.000001", "中证500": "sh.000905", "创业板指": "sz.399006"}
us = load.us_daily(["^NDX", "^GSPC", "SPY", "QQQ"])
series = {}
for n, c in A.items():
    g = ix[ix.code == c].set_index("date")
    series[n] = (g["close"].astype(float), g["amount"].astype(float))
for n, t, vt in [("纳指100", "^NDX", "QQQ"), ("标普500", "^GSPC", "SPY")]:
    p = us[us.ticker == t].set_index("date")["close"]
    v = us[us.ticker == vt].set_index("date")
    series[n] = (p, (v["close"] * v["volume"]).reindex(p.index))   # 用ETF成交额代表市场成交额


def perf(r):
    eq = (1 + r).cumprod()
    yrs = len(r) / 250
    return eq.iloc[-1] ** (1 / yrs) - 1, (eq / eq.cummax() - 1).min()


rows, br_rows, heat_rows = [], [], []
for n, (p, amt) in series.items():
    p = p.dropna()
    ma = p.rolling(200).mean()
    r = p.pct_change()
    w = p.loc[START:END].index
    w = w[w >= ma.dropna().index[0]]
    hold = (p > ma).shift(1).reindex(w).fillna(False)
    bh = perf(r.reindex(w).fillna(0))
    flt = perf((r.reindex(w) * hold).fillna(0))
    rows.append({"指数": n, "一直拿：年化": bh[0], "一直拿：最大回撤": bh[1], "只在200日线上方持有：年化": flt[0],
                 "只在200日线上方持有：最大回撤": flt[1], "持仓时间占比": hold.mean(), "年化提升": flt[0] - bh[0]})
    # 跌破事件
    f = pd.DataFrame({"px": p, "ma200": ma}).dropna()
    pxa = f.px.to_numpy()
    for t0 in bear.breaks(f):
        if f.index[t0] < pd.Timestamp(START):
            continue
        br_rows.append({"指数": n, "t0": f.index[t0].date(),
                        "fwd6m": pxa[t0 + 126] / pxa[t0] - 1 if t0 + 126 < len(pxa) else np.nan,
                        "fwd12m": pxa[t0 + 252] / pxa[t0] - 1 if t0 + 252 < len(pxa) else np.nan,
                        "mdd12m": pxa[t0:t0 + 253].min() / pxa[t0] - 1 if t0 + 252 < len(pxa) else np.nan})
    # 成交额热度
    a = amt.reindex(p.index)
    heat = a.rolling(20).mean() / a.rolling(250).mean()
    d = pd.DataFrame({"heat": heat, "f3": p.shift(-63) / p - 1, "f6": p.shift(-126) / p - 1}).loc[START:END].dropna()
    d["q"] = pd.qcut(d.heat, 5, labels=["最冷", "偏冷", "中间", "偏热", "最热"])
    g = d.groupby("q", observed=True).agg(热度均值=("heat", "mean"), 之后3个月平均=("f3", "mean"), 之后6个月平均=("f6", "mean"),
                                          之后6个月上涨概率=("f6", lambda s: (s > 0).mean()))
    g["指数"] = n
    heat_rows.append(g.reset_index())

pd.set_option("display.width", 250)
t = pd.DataFrame(rows).set_index("指数")
print("== 1) 周期过滤（2006–2026）"); print(t.map(lambda x: f"{x:+.1%}" if isinstance(x, float) else x).to_string())
b = pd.DataFrame(br_rows)
print("\n== 2) 跌破200日线（先站稳20天，再收盘跌到线下2%以上）之后")
print(b.dropna(subset=["fwd12m"]).groupby("指数").agg(次数=("t0", "size"), 一年后上涨占=("fwd12m", lambda s: f"{(s > 0).mean():.0%}"),
      一年后中位=("fwd12m", lambda s: f"{s.median():+.0%}"), 再跌超15占=("mdd12m", lambda s: f"{(s <= -0.15).mean():.0%}")).to_string())
h = pd.concat(heat_rows)
print("\n== 3) 成交额热度分五档 → 之后的平均涨跌（2006–2026，每天一个样本，样本高度重叠）")
for n, g in h.groupby("指数", sort=False):
    print(f"\n{n}"); print(g.drop(columns="指数").set_index("q").map(lambda x: f"{x:+.1%}" if abs(x) < 5 else f"{x:.2f}").to_string())
b.to_csv("ashare_breaks.csv", index=False)
