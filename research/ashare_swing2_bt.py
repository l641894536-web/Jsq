"""A股被套之后的高抛低吸 vs 一直拿着（事件同 ashare_swing_bt.py：跌到一年高点70%以下，手里1份，看到250天后）。
近5年（2021-11→2025-10 起点，前后两段）为主；2016-07→2021-10 起点当"没看过的数据"复核（规则是在近5年上定的）。
每次卖出/买回都扣 0.15% 成本。只要从这轮最低点涨了50%（算反转），之后就不再卖，一直拿到底。
"像反弹（容易失败）"评分：下面7条对上几条（第一波反弹时近5年两段方向都一致的特征）：
  大盘(全A等权)在200日线下；跌得深(低点不到一年高点55%)；从低点到现在≤10天(反弹快)；情绪温度比前5天平均高(升温)；
  它所在行业从它的低点以来涨了5%以上；它还在60日线下；最近5天成交额没超过低点时60日均额的1.5倍(没放量)。
  对上 ≤3 条 = 像反弹；≥6 条 = 像反转。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, events, MID, H, pct

COST = 0.0015


def arrays(W):
    adj = W["adj"]
    A = pd.DataFrame(adj)
    X = dict(hi=A.rolling(250, min_periods=200).max().to_numpy(), ma60=A.rolling(60, min_periods=45).mean().to_numpy(),
             a5=pd.DataFrame(W["amt"]).rolling(5, min_periods=3).mean().to_numpy(), a60=pd.DataFrame(W["amt"]).rolling(60, min_periods=40).mean().to_numpy())
    ew = W["ref"]["全A等权"]; X["ew"] = ew; X["ewma"] = pd.Series(ew).rolling(200, min_periods=150).mean().to_numpy()
    X["temp"] = W["s"]["温度"].to_numpy(float); X["p5"] = W["s"]["prev5"].to_numpy(float)
    return X


def score(W, X, j, t, L, tL):
    c = W["adj"][:, j]; ik = W["ind"][j]; ii = W["ind_ix"].get(ik, X["ew"])
    a60 = X["a60"][tL, j]
    f = [X["ew"][t] < X["ewma"][t], L / X["hi"][tL, j] - 1 <= -0.45, t - tL <= 10, X["temp"][t] > X["p5"][t],
         ii[t] / ii[tL] - 1 >= 0.05, c[t] < X["ma60"][t, j], not (np.isfinite(a60) and a60 > 0 and X["a5"][t, j] / a60 >= 1.5)]
    return sum(bool(x) for x in f)


def sim(W, X, i, j, sell, buy, frac=1.0, chase=0.08):
    """sell(t, c, L, tL, peak) -> 是否卖；buy(t, c, Ls, ps) -> 是否买回。返回 (收益, 卖出次数, [卖价/前后20天最高])。"""
    c = W["adj"][:, j]; end = i + H; p0 = c[i]
    u, cash = 1.0, 0.0; out = False
    L, tL, peak = p0, i, p0; locked = False; Ls = ps = None; n = 0; qual = []
    for t in range(i + 1, end + 1):
        x = c[t]
        if not np.isfinite(x): continue
        if x < L: L, tL, peak = x, t, x
        peak = max(peak, x)
        if not locked and x >= L * 1.5:
            locked = True
        if not out:
            if not locked and sell(t, x, L, tL, peak):
                q = u * frac; cash += q * x * (1 - COST); u -= q; out = True; Ls, ps = L, x; n += 1
                w = c[max(i, t - 20):min(end, t + 20) + 1]; qual.append(x / np.nanmax(w))
        else:
            if buy(t, x, Ls, ps) or (chase and x >= ps * (1 + chase)) or (locked and x >= ps):
                u += cash / x * (1 - COST); cash = 0.0; out = False; L, tL, peak = x, t, x
    return (u * c[end] + cash) / p0 - 1, n, qual


def strategies(W, X):
    sc = lambda j: (lambda t, L, tL: score(W, X, j, t, L, tL))
    S = {}
    S["一直拿着"] = None
    S["反弹15%卖，回到低点附近接，涨过卖价8%追回"] = (lambda j: lambda t, x, L, tL, pk: x >= L * 1.15, lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08)
    S["反弹15%卖，回到低点附近接，不追"] = (lambda j: lambda t, x, L, tL, pk: x >= L * 1.15, lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0)
    S["反弹15%卖，比卖价跌10%接，涨8%追回"] = (lambda j: lambda t, x, L, tL, pk: x >= L * 1.15, lambda j: lambda t, x, Ls, ps: x <= ps * 0.90, 0.08)
    S["反弹25%卖，回到低点附近接，涨8%追回"] = (lambda j: lambda t, x, L, tL, pk: x >= L * 1.25, lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08)
    S["涨15%后从高点回落8%卖（卖在回头时）"] = (lambda j: lambda t, x, L, tL, pk: pk >= L * 1.15 and x <= pk * 0.92, lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08)
    S["碰到60日线卖（离低点≥10%）"] = (lambda j: lambda t, x, L, tL, pk: x >= L * 1.10 and x >= X["ma60"][t, j], lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08)
    S["情绪高潮退潮时卖（温度≥75且回落，离低点≥10%），冰点附近接"] = (
        lambda j: lambda t, x, L, tL, pk: x >= L * 1.10 and X["temp"][t] >= 75 and X["temp"][t] < X["p5"][t],
        lambda j: lambda t, x, Ls, ps: X["temp"][t] <= 30 or x <= Ls * 1.05, 0.08)
    for k in (3, 4):
        S[f"反弹15%且像反弹(评分≤{k})才卖，低点附近接，涨8%追回"] = (
            lambda j, k=k: lambda t, x, L, tL, pk: x >= L * 1.15 and score(W, X, j, t, L, tL) <= k,
            lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08)
    S["回落8%卖且像反弹(评分≤3)，低点附近接，涨8%追回"] = (
        lambda j: lambda t, x, L, tL, pk: pk >= L * 1.15 and x <= pk * 0.92 and score(W, X, j, t, L, tL) <= 3,
        lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08)
    S["反弹15%且像反弹(评分≤3)卖一半，低点附近接回"] = (
        lambda j: lambda t, x, L, tL, pk: x >= L * 1.15 and score(W, X, j, t, L, tL) <= 3,
        lambda j: lambda t, x, Ls, ps: x <= Ls * 1.05, 0.08, 0.5)
    return S


def run(W, R, lab):
    X = arrays(W); S = strategies(W, X)
    res = {}; Q = {}; NT = {}
    for nm, spec in S.items():
        vals, nts, qs = [], [], []
        for i, j in zip(R.i, R.j):
            if spec is None:
                c = W["adj"][:, j]; vals.append(c[i + H] / c[i] - 1); nts.append(0); continue
            sf, bf, ch = spec[0](j), spec[1](j), spec[2]
            frac = spec[3] if len(spec) > 3 else 1.0
            v, n, q = sim(W, X, i, j, sf, bf, frac, ch); vals.append(v); nts.append(n); qs += q
        res[nm] = np.array(vals); NT[nm] = np.mean(nts); Q[nm] = np.mean(qs) if qs else np.nan
    h = res["一直拿着"]; per = R.per.to_numpy()
    out = []
    for nm, v in res.items():
        d = v - h
        row = {"做法": nm, "平均": pct(v.mean()), "中位": pct(np.median(v)), "最差10%": pct(np.quantile(v, .1)), "比拿着多": pct(d.mean()),
               "赢拿着的比例": f"{(d > 0.001).mean():.0%}", "每次卖几回": f"{NT[nm]:.1f}", "卖价/前后20天最高": f"{Q[nm]:.0%}" if np.isfinite(Q[nm]) else "—"}
        for p in ["前半", "后半"]:
            if (per == p).any(): row[p + "比拿着"] = pct(d[per == p].mean())
        out.append(row)
    print(f"\n######## {lab}：{len(R):,} 次被套30%，手里1份拿到250天")
    print(pd.DataFrame(out).to_string(index=False))
    return res


if __name__ == "__main__":
    which = os.environ.get("WHICH", "main")
    if which == "main":
        W = world(); R = pd.read_pickle("/tmp/_swing_events.pkl") if os.path.exists("/tmp/_swing_events.pkl") else events(W)
        res = run(W, R, "近5年（2021-11→2025-10 起点）")
    else:
        W = world("2015-01-01"); R = events(W, pd.Timestamp("2016-07-01"), pd.Timestamp("2021-10-31"))
        R.to_pickle("/tmp/_swing_events_old.pkl")
        res = run(W, R, "复核：2016-07→2021-10 起点（规则没在这段上定过）")
    pd.to_pickle({k: v for k, v in res.items()}, f"/tmp/_swing_res_{which}.pkl")
