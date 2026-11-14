"""【已被 ashare_top5_bt.py 取代：本脚本原先卖半时把股数写死为0.5（已修正），且按当天收盘成交；结论以 top5 为准】
在高位"涨过头时卖一半、回落后买回"（卖在上涨途中，不是等回落）：只用当天能知道的数。
事件同 ashare_top_bt.py；满仓时 收盘/60日线 ≥ k → 卖一半；半仓时 收盘/60日线 ≤ b → 买回。k = 1.3/1.4/1.5，b = 1.10/1.0。
另：大盘情绪温度≥80 卖一半、≤50 买回。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct
from ashare_top_bt import find, H, COST


def sim(c, sellf, buyf, i):
    p0 = c[i]; u = 1.0; cash = 0.0; full = True; n = 0
    for t in range(i + 1, i + H + 1):
        x = c[t]
        if not np.isfinite(x): continue
        if full and sellf(t, x):
            q = u / 2; cash = q * x * (1 - COST); u -= q; full = False; n += 1   # 2026-11-14 修正：原来写死 u = 0.5，买回后股数≠1 时记错
        elif not full and buyf(t, x):
            u += cash / x * (1 - COST); cash = 0; full = True
    return (u * c[i + H] + cash) / p0 - 1, n


def run(W, R, lab):
    adj = W["adj"]; ma60 = pd.DataFrame(adj).rolling(60, min_periods=45).mean().to_numpy()
    temp = W["s"]["温度"].to_numpy(float)
    per = R.per.to_numpy(); el = (R.ind == "C39").to_numpy()
    specs = {"一直拿着": None}
    for k in (1.3, 1.4, 1.5):
        for b in (1.10, 1.0):
            specs[f"比60日线高{int(round((k-1)*100))}%卖一半，回到60日线{'+10%' if b > 1 else ''}买回"] = (k, b)
    specs["情绪温度≥80卖一半，≤50买回"] = "temp"
    res = {}
    for nm, sp in specs.items():
        v, ns = [], []
        for i, j in zip(R.i, R.j):
            c = adj[:, j]
            if sp is None: v.append(c[i + H] / c[i] - 1); ns.append(0); continue
            if sp == "temp":
                r, n = sim(c, lambda t, x: temp[t] >= 80, lambda t, x: temp[t] <= 50, i)
            else:
                k, b = sp
                r, n = sim(c, lambda t, x, j=j, k=k: x >= ma60[t, j] * k, lambda t, x, j=j, b=b: x <= ma60[t, j] * b, i)
            v.append(r); ns.append(n)
        res[nm] = (np.array(v), np.mean(ns))
    h = res["一直拿着"][0]; out = []
    for nm, (v, n) in res.items():
        d = v - h
        row = {"做法": nm, "平均": pct(v.mean()), "最差10%": pct(np.quantile(v, .1)), "比拿着多": pct(d.mean()), "赢拿着": f"{(d > 0.001).mean():.0%}", "一年卖几次": f"{n:.1f}"}
        for p in ["前半", "后半"]:
            if (per == p).any(): row[p] = pct(d[per == p].mean())
        row["电子"] = pct(d[el].mean()); out.append(row)
    print(f"\n######## {lab}：{len(R):,} 次")
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    if os.environ.get("WHICH", "main") == "main":
        W = world(); run(W, find(W, pd.Timestamp("2021-11-01"), pd.Timestamp("2025-10-31")), "近5年")
    else:
        W = world("2015-01-01"); run(W, find(W, pd.Timestamp("2016-07-01"), pd.Timestamp("2021-10-31")), "复核 2016-07→2021-10")
