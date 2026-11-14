"""在高位"回落卖一半、再创新高买回、反复做"（只用当天能知道的：到那天为止的最高收盘、过去60天最高、过去20天波动）。
事件同 ashare_top_bt.py（大涨50%后创一年新高），手里1份看250天，每次买卖扣0.15%。
做法：满仓时，收盘比"这次买入后的最高收盘"低 X → 卖一半；半仓时，收盘创60日新高 → 买回满仓（最高点从这里重新算）。
X = 10% / 15% / 20% / 按波动（20天日波动的3倍，限制在8%~30%）。另列"全卖+创新高买回"对照。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct
from ashare_top_bt import find, H, COST


def sim(c, vol, h60, i, thr, frac=0.5, end=None, log=None, dates=None, raw=None):
    end = end if end is not None else i + H
    p0 = c[i]; u = 1.0; cash = 0.0; full = True; pk = p0; n = 0
    for t in range(i + 1, end + 1):
        x = c[t]
        if not np.isfinite(x): continue
        if full:
            pk = max(pk, x)
            th = thr if thr != "vol" else float(np.clip(3 * vol[t], 0.08, 0.30))
            if x <= pk * (1 - th):
                q = u * frac; cash += q * x * (1 - COST); u -= q; full = False; n += 1
                if log is not None: log.append((dates[t].date(), "卖" + ("一半" if frac < 1 else "全部"), raw[t], f"比买入后最高 {pk:.4g} 低 {1-x/pk:.0%}"))
        elif x >= h60[t]:
            u += cash / x * (1 - COST); cash = 0.0; full = True; pk = x
            if log is not None: log.append((dates[t].date(), "买回", raw[t], "创60日新高"))
    return (u * c[end] + cash) / p0 - 1, n


def run(W, R, lab):
    adj = W["adj"]; A = pd.DataFrame(adj)
    vol = A.pct_change(fill_method=None).rolling(20, min_periods=15).std().to_numpy()
    h60 = A.rolling(60, min_periods=40).max().shift(1).to_numpy()
    per = R.per.to_numpy(); el = (R.ind == "C39").to_numpy()
    res = {}
    specs = [("一直拿着", None, 0)] + [(f"回落{int(x*100)}%卖一半，创新高买回", x, 0.5) for x in (0.10, 0.15, 0.20)] + \
            [("按波动回落卖一半，创新高买回", "vol", 0.5), ("回落10%全卖，创新高买回", 0.10, 1.0), ("回落20%全卖，创新高买回", 0.20, 1.0)]
    for nm, thr, frac in specs:
        v, ns = [], []
        for i, j in zip(R.i, R.j):
            c = adj[:, j]
            if thr is None: v.append(c[i + H] / c[i] - 1); ns.append(0); continue
            r, n = sim(c, vol[:, j], h60[:, j], i, thr, frac); v.append(r); ns.append(n)
        res[nm] = (np.array(v), np.mean(ns))
    h = res["一直拿着"][0]
    out = []
    for nm, (v, n) in res.items():
        d = v - h
        row = {"做法": nm, "平均": pct(v.mean()), "中位": pct(np.median(v)), "最差10%": pct(np.quantile(v, .1)), "比拿着多": pct(d.mean()),
               "赢拿着": f"{(d > 0.001).mean():.0%}", "一年卖几次": f"{n:.1f}"}
        for p in ["前半", "后半"]:
            if (per == p).any(): row[p] = pct(d[per == p].mean())
        row["电子"] = pct(d[el].mean()); row["电子最差10%"] = pct(np.quantile(v[el], .1))
        out.append(row)
    print(f"\n######## {lab}：{len(R):,} 次（电子 {el.sum()}）")
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    if os.environ.get("WHICH", "main") == "main":
        W = world(); run(W, find(W, pd.Timestamp("2021-11-01"), pd.Timestamp("2025-10-31")), "近5年")
    else:
        W = world("2015-01-01"); run(W, find(W, pd.Timestamp("2016-07-01"), pd.Timestamp("2021-10-31")), "复核 2016-07→2021-10")
