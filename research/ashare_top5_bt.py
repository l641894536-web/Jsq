"""A股大涨后在高位：三组完整记账对照（修正 top3/top4 卖出后股数写死 0.5 的错误；以本脚本为准）。
事件：收盘创一年新高且比120天低点涨50%以上（ashare_top_bt.find），事件当天收盘时持有市值1的股票，看到之后第250个交易日收盘。
执行：收盘出信号 → 下一个可成交交易日开盘成交（当天停牌或一字板 high==low 视为不能成交，顺延）；
      卖出 = 当时实际股数的一半；买回 = 用全部现金按开盘价买；每笔扣 0.15%。每天按收盘记净值。
三组：
  A 一直持有
  B 偏离60日线40%卖半：满仓时 收盘 ≥ 60日线×1.4 → 卖半；半仓时 收盘 ≤ 60日线 → 买回；可重复
  C 结构破坏后减仓：满仓时 收盘 < 60日线 且 收盘 < 前20个交易日最低收盘 → 卖半；半仓时 收盘 > 前60个交易日最高收盘 → 买回；可重复
指标：净收益（平均/中位/最差10%）、每日净值最大回撤、平均持股比例、卖出次数、买回价比卖出价高的比例、每轮卖-买后股数变化、比持有多的平均值及按月份分块自助法 95% 区间。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct, MID
from ashare_top_bt import find, H

COST = 0.0015


def prep(W):
    P = __import__("apanel").build(extra=True)
    d_all = pd.DatetimeIndex(pd.to_datetime(P["dates"]))
    t0 = d_all.searchsorted(W["dates"][0])
    sl = lambda M: np.asarray(M[t0:t0 + len(W["dates"])], dtype="float64")
    close, opn, hi, lo = sl(P["close"]), sl(P["open"]), sl(P["high"]), sl(P["low"])
    adj = W["adj"]
    with np.errstate(invalid="ignore", divide="ignore"):
        f = adj / close                              # 当天复权系数
        aopen = opn * f
    tradable = np.isfinite(aopen) & (aopen > 0) & np.isfinite(hi) & np.isfinite(lo) & (hi > lo)
    A = pd.DataFrame(adj)
    X = dict(adj=adj, aopen=aopen, tradable=tradable,
             ma60=A.rolling(60, min_periods=45).mean().to_numpy(),
             lo20=A.rolling(20, min_periods=15).min().shift(1).to_numpy(),
             hi60=A.rolling(60, min_periods=40).max().shift(1).to_numpy())
    return X


def simulate(c, o, ok, sell_sig, buy_sig, i, end):
    """返回 (净值序列, 交易列表)。资金1、股数 1/c[i]。"""
    sh = 1.0 / c[i]; cash = 0.0; full = True; pending = None
    eq = np.empty(end - i + 1); eq[0] = 1.0; trades = []
    for k, t in enumerate(range(i + 1, end + 1), start=1):
        if pending is not None and ok[t]:
            px = o[t]
            if pending == "S":
                q = sh / 2; cash += q * px * (1 - COST); sh -= q; full = False
                trades.append(("S", t, px, q))
            else:
                b = cash * (1 - COST) / px; sh += b; cash = 0.0; full = True
                trades.append(("B", t, px, b))
            pending = None
        x = c[t]
        eq[k] = sh * x + cash
        if pending is None and t < end:
            if full and sell_sig(t): pending = "S"
            elif not full and buy_sig(t): pending = "B"
    return eq, trades


def stats_one(eq, trades, c, i, end):
    path = eq
    mdd = float(np.min(path / np.maximum.accumulate(path) - 1))
    # 持股比例：每天收盘股票市值 / 净值（重新按交易推一遍股数）
    sh = 1.0 / c[i]; cash = 0.0; ti = 0; expo = []
    tr = sorted(trades, key=lambda z: z[1])
    for t in range(i + 1, end + 1):
        while ti < len(tr) and tr[ti][1] == t:
            s, _, px, q = tr[ti]
            if s == "S": sh -= q; cash += q * px * (1 - COST)
            else: sh += q; cash = 0.0
            ti += 1
        v = sh * c[t] + cash
        expo.append(sh * c[t] / v if v > 0 else np.nan)
    rt = []   # 每轮 卖→买：买回价/卖出价-1、股数变化
    for a, b in zip(tr, tr[1:]):
        if a[0] == "S" and b[0] == "B":
            rt.append((b[2] / a[2] - 1, (b[3] - a[3]) / (2 * a[3])))   # 卖前股数 = 2*卖出股数
    return dict(ret=path[-1] - 1, mdd=mdd, expo=float(np.nanmean(expo)), nsell=sum(1 for z in trades if z[0] == "S"), rt=rt)


def run(W, R, lab):
    X = prep(W); adj, o, ok = X["adj"], X["aopen"], X["tradable"]; ma60, lo20, hi60 = X["ma60"], X["lo20"], X["hi60"]
    rules = {
        "A 一直持有": None,
        "B 偏离60日线40%卖半": (lambda j: (lambda t: adj[t, j] >= 1.4 * ma60[t, j]), lambda j: (lambda t: adj[t, j] <= ma60[t, j])),
        "C 结构破坏后减仓": (lambda j: (lambda t: adj[t, j] < ma60[t, j] and adj[t, j] < lo20[t, j]), lambda j: (lambda t: adj[t, j] > hi60[t, j])),
    }
    res = {k: [] for k in rules}
    for i, j in zip(R.i, R.j):
        c = adj[:, j]; end = i + H
        for nm, rl in rules.items():
            if rl is None:
                eq = c[i:end + 1] / c[i]; tr = []
            else:
                eq, tr = simulate(c, o[:, j], ok[:, j], rl[0](j), rl[1](j), i, end)
            res[nm].append(stats_one(eq, tr, c, i, end))
    per = R.per.to_numpy(); el = (R.ind == "C39").to_numpy(); mon = R.d.dt.to_period("M").astype(str).to_numpy()
    h = np.array([z["ret"] for z in res["A 一直持有"]]); hm = np.array([z["mdd"] for z in res["A 一直持有"]])
    rng = np.random.default_rng(7); months = np.unique(mon); idx = {m: np.where(mon == m)[0] for m in months}

    def ci(d):
        bs = []
        for _ in range(1000):
            pick = rng.choice(months, len(months)); ii = np.concatenate([idx[m] for m in pick]); bs.append(d[ii].mean())
        return np.percentile(bs, [2.5, 97.5])

    out = []
    for nm, L in res.items():
        r = np.array([z["ret"] for z in L]); m = np.array([z["mdd"] for z in L]); e = np.array([z["expo"] for z in L])
        ns = np.array([z["nsell"] for z in L]); rt = [x for z in L for x in z["rt"]]
        d = r - h; lo_, hi_ = ci(d) if nm != "A 一直持有" else (0, 0)
        row = {"做法": nm, "净收益平均": pct(r.mean()), "中位": pct(np.median(r)), "最差10%": pct(np.quantile(r, .1)),
               "最大回撤平均": pct(m.mean()), "回撤最差10%": pct(np.quantile(m, .1)), "平均持股": f"{e.mean():.0%}",
               "卖出次数": f"{ns.mean():.2f}", "买回比卖出贵": f"{np.mean([x[0] > 0 for x in rt]):.0%}" if rt else "—",
               "每轮股数变化": pct(np.mean([x[1] for x in rt])) if rt else "—",
               "比持有多": pct(d.mean()), "95%区间": f"{pct(lo_)}~{pct(hi_)}" if nm != "A 一直持有" else "—",
               "多赚的那部分/少赚的那部分": f"{d[d > 0].sum():.0f}/{-d[d < 0].sum():.0f}" if nm != "A 一直持有" else "—"}
        for p in ["前半", "后半"]:
            if (per == p).any(): row[p + "比持有"] = pct(d[per == p].mean())
        row["电子比持有"] = pct(d[el].mean())
        out.append(row)
    print(f"\n######## {lab}：{len(R):,} 次（电子 {el.sum()}），每次资金1、看250个交易日")
    T = pd.DataFrame(out)
    print(T.drop(columns=[c for c in T.columns if c.endswith("比持有") or c == "电子比持有"]).to_string(index=False))
    print(T[["做法"] + [c for c in T.columns if c.endswith("比持有") or c == "电子比持有"]].to_string(index=False))
    return res


if __name__ == "__main__":
    which = os.environ.get("WHICH", "main")
    W = world("2015-01-01")
    if which == "main":
        run(W, find(W, pd.Timestamp("2021-11-01"), pd.Timestamp("2025-10-31")), "近5年（2021-11→2025-10 起点）")
    else:
        run(W, find(W, pd.Timestamp("2016-07-01"), pd.Timestamp("2021-10-31")), "复核 2016-07→2021-10")


def static_mix(W, R, w):
    """对照：事件当天起固定 w 买股票、1-w 拿现金，不再调整。"""
    adj = W["adj"]; r, m = [], []
    for i, j in zip(R.i, R.j):
        p = adj[i:i + H + 1, j] / adj[i, j]; eq = (1 - w) + w * p
        r.append(eq[-1] - 1); m.append(np.min(eq / np.maximum.accumulate(eq) - 1))
    return np.array(r), np.array(m)
