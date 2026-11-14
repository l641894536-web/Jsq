"""候选规则"高于60日线40%卖半、跌回60日线买回"在科技股上的检验（接 ashare_top5_bt.py 的完整记账）。
相对 top5 的改动：
  ① 股票池固定：证监会行业 C39（计算机、通信和其他电子设备制造）+ I63（电信、广播电视和卫星传输服务）+ I64（互联网和相关服务）+ I65（软件和信息技术服务）；
     全A只作对照；ETF 另见 etf_run（Yahoo 日线）。
  ② 开盘能否成交按涨跌停价判断（不再用全天 high>low）：涨跌停幅度 主板10%、创业板2020-08-24起20%、科创板20%、ST 5%（创业板/科创板ST按20%）；
     价格 = 前收×(1±幅度) 四舍五入到分。开盘价在跌停价 → 当天不能卖；开盘价在涨停价 → 当天不能买；停牌也不能；都顺延到下一个能成交的开盘。
  ③ 择时贡献：对照"事件当天起固定 94% 拿股票、6% 现金"（94% ≈ 规则在各股票池的平均持股，事前就能定）。
     不用"每个事件自己的平均持股"去配：那个比例要事后才知道，规则在暴涨的事件里持股低，会让对照组恰好在涨得多的事件里少拿，高估择时。
  ④ 区间：事件各看250个交易日、相邻月份大量重叠。先按事件起始月份取平均得月度序列，再用 Newey-West（12个月滞后）和
     12个月移动块自助法（循环）两种方法算95%区间，取更宽的那个；事件数平均和月份平均都列。
其余同 top5：事件当天收盘持有资金1，看250个交易日；卖出 = 当时股数一半；买回用全部现金；每笔0.15%；每日收盘净值。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct, MID
from ashare_top_bt import find, H

COST = 0.0015
TECH = {"C39", "I63", "I64", "I65"}
W_FIX = 0.94
r2 = lambda x: np.floor(x * 100 + 0.5 + 1e-6) / 100      # 交易所四舍五入到分；+1e-6 防浮点误差（21.65×0.9=19.485 要得 19.49）
r3 = lambda x: np.floor(x * 1000 + 0.5 + 1e-6) / 1000    # ETF 价格到厘


def prep(W):
    import apanel
    P = apanel.build(extra=True)
    d_all = pd.DatetimeIndex(pd.to_datetime(P["dates"]))
    t0 = d_all.searchsorted(W["dates"][0]); n = len(W["dates"])
    sl = lambda k: np.asarray(P[k][t0:t0 + n], dtype="float64")
    close, opn, pre, st, ts = sl("close"), sl("open"), sl("preclose"), sl("isST"), sl("tradestatus")
    opn, pre = np.round(opn, 2), np.round(pre, 2)     # apanel 是 float32，先还原到分，否则涨跌停价会算错（sz.002835 2024-04-23）
    adj = W["adj"]; codes = np.array(W["codes"]); dates = W["dates"]
    star = np.array([c.startswith("sh.688") for c in codes]); gem = np.array([c.startswith("sz.300") or c.startswith("sz.301") for c in codes])
    after = (dates >= pd.Timestamp("2020-08-24"))[:, None]
    wide = star[None, :] | (gem[None, :] & after)
    lim = np.where(wide, 0.20, np.where(st == 1, 0.05, 0.10))
    lu, ld = r2(pre * (1 + lim)), r2(pre * (1 - lim))
    ok = (ts == 1) & np.isfinite(opn) & (opn > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        aopen = opn * adj / close
    A = pd.DataFrame(adj)
    return dict(adj=adj, aopen=aopen, can_sell=ok & (opn > ld + 0.0005), can_buy=ok & (opn < lu - 0.0005),
                ma60=A.rolling(60, min_periods=45).mean().to_numpy())


def simulate(c, o, cs, cb, sell_sig, buy_sig, i, end):
    sh = 1.0 / c[i]; cash = 0.0; full = True; pending = None
    eq = np.empty(end - i + 1); eq[0] = 1.0; ex = np.empty(end - i + 1); ex[0] = 1.0; trades = []
    for k, t in enumerate(range(i + 1, end + 1), start=1):
        if pending == "S" and cs[t]:
            q = sh / 2; cash += q * o[t] * (1 - COST); sh -= q; full = False; trades.append(("S", t, o[t], q)); pending = None
        elif pending == "B" and cb[t]:
            b = cash * (1 - COST) / o[t]; sh += b; cash = 0.0; full = True; trades.append(("B", t, o[t], b)); pending = None
        eq[k] = sh * c[t] + cash; ex[k] = sh * c[t] / eq[k] if eq[k] > 0 else np.nan
        if pending is None and t < end:
            if full and sell_sig(t): pending = "S"
            elif not full and buy_sig(t): pending = "B"
    return eq, ex, trades


def mdd(eq):
    return float(np.min(eq / np.maximum.accumulate(eq) - 1))


def events_eval(X, R):
    adj, o, cs, cb, ma60 = X["adj"], X["aopen"], X["can_sell"], X["can_buy"], X["ma60"]
    rows = []
    for i, j in zip(R.i, R.j):
        c = adj[:, j]; end = i + H; p = c[i:end + 1] / c[i]
        eq, ex, tr = simulate(c, o[:, j], cs[:, j], cb[:, j], lambda t: c[t] >= 1.4 * ma60[t, j], lambda t: c[t] <= ma60[t, j], i, end)
        w = float(np.nanmean(ex[1:])); st = (1 - W_FIX) + W_FIX * p
        rt = [(b[2] / a[2] - 1) for a, b in zip(tr, tr[1:]) if a[0] == "S" and b[0] == "B"]
        rows.append(dict(hold=p[-1] - 1, hold_mdd=mdd(p), rule=eq[-1] - 1, rule_mdd=mdd(eq), w=w, stat=st[-1] - 1, stat_mdd=mdd(st),
                         nsell=sum(1 for z in tr if z[0] == "S"), n_rt=len(rt), rt_up=sum(1 for x in rt if x > 0),
                         open_end=bool(tr and tr[-1][0] == "S")))
    D = pd.concat([R.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    D["d_hold"] = D.rule - D.hold; D["d_stat"] = D.rule - D.stat
    return D


def ci_overlap(D, col, L=12, B=2000, seed=11):
    """月度序列（按事件起始月份平均）→ Newey-West(L) 和 L个月循环移动块自助法；返回 (月均, 低, 高, 用了哪种)。"""
    s = D.groupby(D.d.dt.to_period("M"))[col].mean()
    x = s.to_numpy(float); n = len(x); mu = x.mean()
    if n < 2 * L:
        return mu, np.nan, np.nan, "月份太少"
    e = x - mu; g0 = e @ e / n; nw = g0
    for l in range(1, L + 1):
        nw += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / n
    se = np.sqrt(max(nw, 0) / n); a1, b1 = mu - 1.96 * se, mu + 1.96 * se
    rng = np.random.default_rng(seed); nb = int(np.ceil(n / L)); bs = np.empty(B)
    for k in range(B):
        st = rng.integers(0, n, nb); ii = (st[:, None] + np.arange(L)[None, :]).ravel() % n
        bs[k] = x[ii[:n]].mean()
    a2, b2 = np.percentile(bs, [2.5, 97.5])
    return (mu, a1, b1, "NW") if (b1 - a1) >= (b2 - a2) else (mu, a2, b2, "块自助")


def report(D, lab):
    print(f"\n######## {lab}：{len(D):,} 次（起始 {D.d.min():%Y-%m} → {D.d.max():%Y-%m}，{D.d.dt.to_period('M').nunique()} 个月）")
    rows = []
    for nm, r, m in [("一直持有", D.hold, D.hold_mdd), ("卖半规则", D.rule, D.rule_mdd), ("固定94%股票", D.stat, D.stat_mdd)]:
        rows.append({"做法": nm, "净收益平均": pct(r.mean()), "中位": pct(r.median()), "最差10%": pct(r.quantile(.1)),
                     "最大回撤平均": pct(m.mean()), "回撤最差10%": pct(m.quantile(.1))})
    print(pd.DataFrame(rows).to_string(index=False))
    rt = D.n_rt.sum()
    print(f"  卖半规则：平均持股 {D.w.mean():.0%}，每次事件卖出 {D.nsell.mean():.2f} 次，触发过的占 {(D.nsell > 0).mean():.0%}；"
          f"卖了又买回 {rt} 轮，其中买回价更贵 {D.rt_up.sum() / max(rt, 1):.0%}；到期时还是半仓 {D.open_end.mean():.0%}")
    out = []
    for col, nm in [("d_hold", "卖半 − 一直持有"), ("d_stat", "卖半 − 固定94%股票（择时部分）")]:
        mu, lo, hi, how = ci_overlap(D, col)
        row = {"比较": nm, "事件平均": pct(D[col].mean()), "月份平均": pct(mu), "95%区间": f"{pct(lo)}~{pct(hi)}（{how}）",
               "卖半更好": f"{(D[col] > 0.001).mean():.0%}"}
        for p in ["前半", "后半"]:
            x = D[D.per == p][col]
            if len(x) >= 30: row[p] = pct(x.mean())
        out.append(row)
    for col, nm in [("rule_mdd", "回撤：卖半"), ("stat_mdd", "回撤：固定同仓位")]:
        pass
    print(pd.DataFrame(out).to_string(index=False))
    print(f"  回撤（平均）：持有 {pct(D.hold_mdd.mean())}，卖半 {pct(D.rule_mdd.mean())}，固定94% {pct(D.stat_mdd.mean())}")


def clean_etf(x):
    """Yahoo 的A股ETF日线：拆分没调整、还有单日按旧口径的错价。ETF涨跌停最多20%，单日超过±30%的变动都不是真行情。
    ① 单日错价：c[t]/c[t-1] 偏离超过30%，而 c[t+1] 又回到 c[t-1] 的±25% 以内 → 当天作废（开收都设 NaN）；
    ② 拆分/合并：剩下的单日跌超30% → 之前的价格除以 round(前收/今收)（不接近整数就用原比值）；涨超30%同理乘回去。"""
    x = x.copy(); c = x.close.to_numpy(float).copy(); o = x.open.to_numpy(float).copy()
    for _ in range(3):
        idx = np.where(np.isfinite(c))[0]
        for a, b, d_ in zip(idx, idx[1:], idx[2:]):
            q1, q2 = c[b] / c[a], c[d_] / c[a]
            if (q1 > 1.3 or q1 < 0.7) and 0.75 < q2 < 1.25:
                c[b] = np.nan; o[b] = np.nan
    idx = np.where(np.isfinite(c))[0]
    for a, b in zip(idx, idx[1:]):
        q = c[b] / c[a]
        if q < 0.7 or q > 1.43:
            r = 1 / q if q < 1 else q; f = round(r) if abs(r / round(r) - 1) < 0.15 else r
            if q < 1: c[:b] /= f; o[:b] /= f
            else: c[:b] *= f; o[:b] *= f
    x["close"] = c; x["open"] = o; x["adj_close"] = c
    return x[np.isfinite(x.close)]


def etf_run(start, until, lab):
    from market_data import load
    tks = ["512760.SS", "512480.SS", "588000.SS", "159995.SZ", "159801.SZ", "515050.SS", "515880.SS", "512720.SS",
           "515000.SS", "159939.SZ", "515980.SS", "159819.SZ", "512330.SS", "159807.SZ", "512980.SS"]
    d = load.us_daily(tks, start="2015-01-01")
    rows = []
    for t, x in d.groupby("ticker"):
        x = clean_etf(x.sort_values("date").set_index("date")); x = x[x.close > 0]
        c = x.adj_close.to_numpy(float); f = c / x.close.to_numpy(float); o = x.open.to_numpy(float) * f
        pre = np.r_[np.nan, x.close.to_numpy(float)[:-1]]; lim = 0.2 if t.startswith("588") else 0.1
        cs = np.isfinite(o) & (x.open.to_numpy(float) > r3(pre * (1 - lim)) + 0.0005); cb = np.isfinite(o) & (x.open.to_numpy(float) < r3(pre * (1 + lim)) - 0.0005)
        A = pd.Series(c); ma60 = A.rolling(60, min_periods=45).mean().to_numpy()
        hi = A.rolling(250, min_periods=200).max().to_numpy(); lo = A.rolling(120, min_periods=100).min().to_numpy()
        ds = x.index; last = -999
        for i in range(len(c) - H):
            if ds[i] < start or ds[i] > until: continue
            if c[i] >= hi[i] - 1e-12 and c[i] >= 1.5 * lo[i] and i - last > 60:
                last = i; end = i + H; p = c[i:end + 1] / c[i]
                eq, ex, tr = simulate(c, o, cs, cb, lambda k: c[k] >= 1.4 * ma60[k], lambda k: c[k] <= ma60[k], i, end)
                w = float(np.nanmean(ex[1:])); s = (1 - W_FIX) + W_FIX * p
                rows.append(dict(etf=t, d=ds[i], hold=p[-1] - 1, rule=eq[-1] - 1, stat=s[-1] - 1, hold_mdd=mdd(p), rule_mdd=mdd(eq),
                                 w=w, trades="；".join(f"{ds[k].date()}{'卖半' if a == 'S' else '买回'}" for a, k, _, _ in tr)))
    E = pd.DataFrame(rows)
    if len(E):
        E["ep"] = E.d.dt.to_period("Q")      # 同一季度起始的事件基本是同一轮行情
    print(f"\n######## ETF（{lab}）：{len(E)} 次'大涨50%后创一年新高'，{E.etf.nunique() if len(E) else 0} 只ETF")
    if len(E):
        E["d_hold"] = E.rule - E.hold; E["d_stat"] = E.rule - E.stat
        print(E[["etf", "d", "hold", "rule", "stat", "hold_mdd", "rule_mdd", "w", "trades"]].assign(
            d=E.d.dt.date, hold=E.hold.map(pct), rule=E.rule.map(pct), stat=E.stat.map(pct), hold_mdd=E.hold_mdd.map(pct), rule_mdd=E.rule_mdd.map(pct), w=E.w.map(lambda v: f"{v:.0%}")).to_string(index=False))
        Q = E.groupby("ep")[["hold", "rule", "stat", "d_hold", "d_stat"]].mean()
        print("  按起始季度合并（同一轮行情只算一次）：" + "；".join(f"{k} {len(E[E.ep == k])}次 卖半−持有{pct(v.d_hold)}" for k, v in Q.iterrows()))
        print(f"  {len(Q)} 轮行情里卖半更好 {(Q.d_hold > 0.001).sum()} 轮、更差 {(Q.d_hold < -0.001).sum()} 轮；轮平均 卖半−持有 {pct(Q.d_hold.mean())}，卖半−固定94% {pct(Q.d_stat.mean())}")
        print(f"  平均：持有 {pct(E.hold.mean())}，卖半 {pct(E.rule.mean())}，固定94% {pct(E.stat.mean())}；卖半−持有 {pct(E.d_hold.mean())}（卖半更好 {(E.d_hold>0.001).mean():.0%}），卖半−固定94% {pct(E.d_stat.mean())}")
    return E


if __name__ == "__main__":
    which = os.environ.get("WHICH", "main")
    if which == "etf":
        os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, "/home/claude/jsq")
        etf_run(pd.Timestamp("2016-07-01"), pd.Timestamp("2025-10-31"), "全部可用，2019年起")
        sys.exit()
    W = world("2015-01-01"); X = prep(W)
    a, b = ("2021-11-01", "2025-10-31") if which == "main" else ("2016-07-01", "2021-10-31")
    R = find(W, pd.Timestamp(a), pd.Timestamp(b))
    D = events_eval(X, R)
    D.to_pickle(f"/tmp/_top6_{which}.pkl")
    tag = "近5年" if which == "main" else "2016-07→2021-10"
    report(D[D.ind.isin(TECH)], f"{tag} 科技池（C39+I63+I64+I65）")
    report(D[D.ind == "C39"], f"{tag} 其中 C39 电子/通信/计算机设备")
    report(D, f"{tag} 全A（对照）")
