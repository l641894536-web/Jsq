"""A股：涨多了怎么卖在高处（还没被套的时候）。
事件：收盘创一年新高、而且比120天内最低点涨了50%以上（大涨后在高位），日均成交≥3000万、非ST、上市满250天；同一只冷却60天。
假设这天手里有1份，看之后250个交易日。每次卖出/买回扣0.15%。
卖法：一直拿着 / 从最高点回落10%、15%、20%、25%卖 / 跌破20日线、60日线卖 / 情绪高潮退潮（温度≥80后回落）卖 / 放量大跌（跌≥7%且成交额≥20日均额2倍）卖
买回：不买回（拿现金） / 重新创60日新高再买回。
近5年（2021-11→2025-10）前后两段 + 2016-07→2021-10 复核；另单看电子/通信设备（证监会 C39，你的持仓所在行业）。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, MID, H, pct

COST = 0.0015


def find(W, start, until):
    adj, U, dates = W["adj"], W["U"], W["dates"]
    T, N = adj.shape
    A = pd.DataFrame(adj)
    hi = A.rolling(250, min_periods=200).max().to_numpy(); lo = A.rolling(120, min_periods=100).min().to_numpy()
    t0, t1 = dates.searchsorted(start), dates.searchsorted(until, side="right")
    rows = []
    for j in range(N):
        c = adj[:, j]; last = -999
        cand = np.where(U[t0:min(t1, T - H), j] & (c[t0:min(t1, T - H)] >= hi[t0:min(t1, T - H), j] - 1e-12) & (c[t0:min(t1, T - H)] >= 1.5 * lo[t0:min(t1, T - H), j]))[0] + t0
        for i in cand:
            if i - last > 60:
                rows.append((i, j)); last = i
    R = pd.DataFrame(rows, columns=["i", "j"]); R["d"] = dates[R.i.to_numpy()]
    R["per"] = np.where(R.d < MID, "前半", "后半"); R["ind"] = W["ind"][R.j.to_numpy()]
    return R


def sim(c, i, sell, reentry, ctx):
    end = i + H; p0 = c[i]; u, cash = 1.0, 0.0; inpos = True; peak = p0; n = 0; sp = []
    for t in range(i + 1, end + 1):
        x = c[t]
        if not np.isfinite(x): continue
        peak = max(peak, x)
        if inpos:
            if sell(t, x, peak):
                cash = u * x * (1 - COST); u = 0; inpos = False; n += 1; sp.append((t, x))
        elif reentry is not None and reentry(t, x):
            u = cash / x * (1 - COST); cash = 0; inpos = True; peak = x
    pk = np.nanmax(c[i:end + 1])
    return (u * c[end] + cash) / p0 - 1, n, (sp[0][1] / pk) if sp else np.nan


def run(W, R, lab):
    adj = W["adj"]; A = pd.DataFrame(adj)
    ma20 = A.rolling(20, min_periods=15).mean().to_numpy(); ma60 = A.rolling(60, min_periods=45).mean().to_numpy()
    h60 = A.rolling(60, min_periods=40).max().shift(1).to_numpy()
    amt = W["amt"]; am20 = pd.DataFrame(amt).rolling(20, min_periods=10).mean().shift(1).to_numpy()
    temp = W["s"]["温度"].to_numpy(float); p5 = W["s"]["prev5"].to_numpy(float)
    ew = W["ref"]["全A等权"]; ewma = pd.Series(ew).rolling(200, min_periods=150).mean().to_numpy()
    def S(j):
        c = adj[:, j]
        sells = {"一直拿着": lambda t, x, pk: False}
        for k in (0.10, 0.15, 0.20, 0.25):
            sells[f"从最高回落{int(k*100)}%卖"] = (lambda k: lambda t, x, pk: x <= pk * (1 - k))(k)
        sells["跌破20日线卖"] = lambda t, x, pk: x < ma20[t, j]
        sells["跌破60日线卖"] = lambda t, x, pk: x < ma60[t, j]
        sells["情绪高潮退潮卖(温度≥80后回落)"] = lambda t, x, pk: np.nanmax(temp[max(0, t - 5):t + 1]) >= 80 and temp[t] < p5[t]
        sells["放量大跌卖(跌7%+、额≥2倍)"] = lambda t, x, pk: x / c[t - 1] - 1 <= -0.07 and amt[t, j] >= 2 * am20[t, j]
        for k in (0.10, 0.15):
            sells[f"回落{int(k*100)}%且大盘在200日线下才卖"] = (lambda k: lambda t, x, pk: x <= pk * (1 - k) and ew[t] < ewma[t])(k)
            sells[f"回落{int(k*100)}%且大盘在200日线上才卖"] = (lambda k: lambda t, x, pk: x <= pk * (1 - k) and ew[t] >= ewma[t])(k)
        sells["回落15%或情绪退潮，先到先卖"] = lambda t, x, pk: x <= pk * 0.85 or (np.nanmax(temp[max(0, t - 5):t + 1]) >= 80 and temp[t] < p5[t])
        return sells
    reent = {"不买回": None, "创60日新高买回": "h60"}
    res = {}; extra = {}
    for i, j in zip(R.i, R.j):
        c = adj[:, j]
        for snm, sf in S(j).items():
            for rnm, rk in reent.items():
                if snm == "一直拿着" and rk is not None: continue
                rf = None if rk is None else (lambda t, x, j=j: x >= h60[t, j])
                v, n, q = sim(c, i, sf, rf, None)
                key = (snm, rnm); res.setdefault(key, []).append(v); extra.setdefault(key, []).append((n, q))
    h = np.array(res[("一直拿着", "不买回")]); per = R.per.to_numpy(); el = (R.ind == "C39").to_numpy()
    pk = np.array([np.nanmax(adj[i:i + H + 1, j]) / adj[i, j] - 1 for i, j in zip(R.i, R.j)])
    print(f"\n######## {lab}：{len(R):,} 次'大涨50%后创新高'（其中电子/通信设备 {el.sum()}），手里1份看250天")
    print(f"之后250天里最高还能再涨 中位 {pct(np.median(pk))}；一直拿着到期 平均 {pct(h.mean())} 中位 {pct(np.median(h))}，到期比最高点回撤 中位 {pct(np.median((1+h)/(1+pk)-1))}")
    out = []
    for key, v in res.items():
        v = np.array(v); d = v - h; nq = extra[key]
        q = np.array([x[1] for x in nq], float)
        row = {"卖法": key[0], "买回": key[1], "平均": pct(v.mean()), "中位": pct(np.median(v)), "最差10%": pct(np.quantile(v, .1)),
               "比拿着多": pct(d.mean()), "赢拿着": f"{(d > 0.001).mean():.0%}", "卖价/之后最高": f"{np.nanmean(q):.0%}" if np.isfinite(q).any() else "—"}
        for p in ["前半", "后半"]:
            if (per == p).any(): row[p] = pct(d[per == p].mean())
        row["电子"] = pct(d[el].mean()) if el.any() else "—"
        out.append(row)
    for k in ("从最高回落10%卖", "从最高回落15%卖", "从最高回落20%卖"):
        v = 0.5 * np.array(res[(k, "不买回")]) + 0.5 * h; d = v - h
        row = {"卖法": "一半" + k + "、一半拿着", "买回": "不买回", "平均": pct(v.mean()), "中位": pct(np.median(v)), "最差10%": pct(np.quantile(v, .1)),
               "比拿着多": pct(d.mean()), "赢拿着": f"{(d > 0.001).mean():.0%}", "卖价/之后最高": "—"}
        for p in ["前半", "后半"]:
            if (per == p).any(): row[p] = pct(d[per == p].mean())
        row["电子"] = pct(d[el].mean()); out.append(row)
    print(pd.DataFrame(out).to_string(index=False))
    # 分大盘：事件当天全A等权在200日线上/下
    dn = np.array([ew[i] < ewma[i] for i in R.i])
    for k in ("从最高回落10%卖", "从最高回落15%卖"):
        v = np.array(res[(k, "不买回")]); d = v - h
        print(f"  {k}（不买回）比拿着：创新高时大盘在200日线下 {pct(d[dn].mean())}（{dn.sum()}次，最差10% 拿着{pct(np.quantile(h[dn],.1))}→{pct(np.quantile(v[dn],.1))}）；"
              f"在线上 {pct(d[~dn].mean())}（{(~dn).sum()}次，最差10% {pct(np.quantile(h[~dn],.1))}→{pct(np.quantile(v[~dn],.1))}）")
    pd.to_pickle({"R": R, "res": res}, f"/tmp/_top_{lab[:2]}.pkl")
    return res


if __name__ == "__main__":
    if os.environ.get("WHICH", "main") == "main":
        W = world(); R = find(W, pd.Timestamp("2021-11-01"), pd.Timestamp("2025-10-31"))
        run(W, R, "近5年（2021-11→2025-10）")
    else:
        W = world("2015-01-01"); R = find(W, pd.Timestamp("2016-07-01"), pd.Timestamp("2021-10-31"))
        run(W, R, "复核 2016-07→2021-10")
