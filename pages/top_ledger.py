"""候选规则前向记账：高于60日线40%卖半、跌回60日线买回（冻结于 2026-11-14，只记 2026-11-16 起新出现的事件）。
规则、事件、成交方式和 research/ashare_top6_bt.py 完全一样，这里不做任何调整；每天从每个事件当天重新按数据推一遍（规则是确定的，结果可复现）。
  事件：收盘创一年新高（250日）且 ≥ 120日最低收盘×1.5；A股要求日均成交（20日）≥3000万、非ST、上市满250个交易日；同一只冷却60个交易日
  卖半：满仓时 收盘 ≥ 60日线×1.4 → 下一个可成交交易日开盘卖当时股数的一半；这一轮不再卖
  买回：半仓时 收盘 ≤ 60日线 → 下一个可成交交易日开盘用全部现金买回
  成交：开盘价在跌停价不能卖、在涨停价不能买（主板10%、创业板/科创板20%、ST 5%；ETF 10%、科创ETF 20%），停牌顺延；每笔 0.15%
  对照：一直持有；固定 94% 股票 + 6% 现金
  范围：科技池（证监会 C39/I63/I64/I65）A股；科技类ETF（Yahoo 日线，清洗拆分和单日错价）；每个事件看 250 个交易日
用法：python3 top_ledger.py --data data --jsq code --site site   （env-page 里跑）
"""
import argparse, json, os, sys
import numpy as np, pandas as pd

RULE = dict(name="高于60日线40%卖半、跌回60日线买回", status="候选（全A两段有效；科技股和ETF回测没证明）", frozen="2026-11-14",
            start="2026-11-16", horizon=250, cost=0.0015, w_fix=0.94, research="research/ashare_top6_bt.py")
TECH = {"C39", "I63", "I64", "I65"}
ETFS = ["512760.SS", "512480.SS", "588000.SS", "159995.SZ", "159801.SZ", "515050.SS", "515880.SS", "512720.SS",
        "515000.SS", "159939.SZ", "515980.SS", "159819.SZ", "512330.SS", "159807.SZ", "512980.SS"]
COST, H, W_FIX = RULE["cost"], RULE["horizon"], RULE["w_fix"]
r2 = lambda x: np.floor(x * 100 + 0.5 + 1e-6) / 100      # 交易所四舍五入到分；+1e-6 防浮点误差（21.65×0.9=19.485 要得 19.49）
r3 = lambda x: np.floor(x * 1000 + 0.5 + 1e-6) / 1000    # ETF 价格到厘
rn = lambda x, n=4: None if x is None or not np.isfinite(x) else round(float(x), n)


def simulate(c, o, cs, cb, sell_sig, buy_sig, i, end):
    """同 research/ashare_top6_bt.simulate。"""
    sh = 1.0 / c[i]; cash = 0.0; full = True; pending = None
    eq = np.empty(end - i + 1); eq[0] = 1.0; trades = []
    for k, t in enumerate(range(i + 1, end + 1), start=1):
        if pending == "S" and cs[t]:
            q = sh / 2; cash += q * o[t] * (1 - COST); sh -= q; full = False; trades.append(("S", t, q)); pending = None
        elif pending == "B" and cb[t]:
            b = cash * (1 - COST) / o[t]; sh += b; cash = 0.0; full = True; trades.append(("B", t, b)); pending = None
        eq[k] = sh * c[t] + cash
        if pending is None and t < end:
            if full and sell_sig(t): pending = "S"
            elif not full and buy_sig(t): pending = "B"
    return eq, trades, full, pending


def mdd(eq):
    return float(np.min(eq / np.maximum.accumulate(eq) - 1))


def run_series(name, code, dates, c, o, raw_open, cs, cb, elig, start_i, out):
    """一只股票/ETF：找事件（冷却从整个窗口算），只记录 start_i 之后的。"""
    A = pd.Series(c)
    hi = A.rolling(250, min_periods=200).max().to_numpy(); lo = A.rolling(120, min_periods=100).min().to_numpy()
    ma60 = A.rolling(60, min_periods=45).mean().to_numpy(); T = len(c); last = -999
    for i in range(250, T):
        if not (elig[i] and np.isfinite(c[i]) and c[i] >= hi[i] - 1e-12 and c[i] >= 1.5 * lo[i] and i - last > 60):
            continue
        last = i
        if i < start_i: continue
        end = min(i + H, T - 1)
        eq, tr, full, pend = simulate(c, o, cs, cb, lambda t: c[t] >= 1.4 * ma60[t], lambda t: c[t] <= ma60[t], i, end)
        p = c[i:end + 1] / c[i]; st = (1 - W_FIX) + W_FIX * p
        out.append(dict(code=code, name=name, d=str(dates[i].date()), days=int(end - i), closed=bool(i + H <= T - 1),
                        hold=rn(p[-1] - 1), rule=rn(eq[-1] - 1), fix94=rn(st[-1] - 1),
                        hold_mdd=rn(mdd(p)), rule_mdd=rn(mdd(eq)), fix94_mdd=rn(mdd(st)),
                        state="满仓" if full else "半仓", pending={"S": "明天开盘卖半", "B": "明天开盘买回"}.get(pend),
                        trades=[[str(dates[t].date()), "卖半" if s == "S" else "买回", rn(raw_open[t], 3)] for s, t, _ in tr]))


def clean_etf(x):
    """同 research/ashare_top6_bt.clean_etf。"""
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
    x["close"] = c; x["open"] = o
    return x[np.isfinite(x.close)]


def build(load, data, start, load_from):
    out_a, out_e = [], []
    ind = pd.read_csv(f"{data}/a_share/meta/industry.csv", dtype=str).set_index("code").industry.str.slice(0, 3)
    codes = [c for c, k in ind.items() if isinstance(k, str) and k in TECH]
    d = load.a_share(start=load_from, codes=codes, adjust=None)
    if len(d):
        piv = lambda col: d.pivot(index="date", columns="code", values=col).sort_index()
        close, opn, pre, pct = (piv(k).astype(float) for k in ("close", "open", "preclose", "pctChg"))
        amt = piv("amount").astype(float); ts = piv("tradestatus").apply(pd.to_numeric, errors="coerce"); st = piv("isST").apply(pd.to_numeric, errors="coerce")
        dates = close.index; cols = close.columns
        traded = (ts.to_numpy() == 1) & np.isfinite(close.to_numpy()) & (amt.fillna(0).to_numpy() > 0)
        ret = np.where(traded, pct.to_numpy() / 100.0, 0.0); adj = np.cumprod(1 + ret, axis=0)
        age = np.cumsum(traded, axis=0)
        am20 = pd.DataFrame(np.where(traded, amt.to_numpy(), np.nan)).rolling(20, min_periods=10).mean().to_numpy()
        isst = np.nan_to_num(st.to_numpy()) == 1
        elig = traded & ~isst & (age >= 250) & (am20 >= 3e7)
        star = np.array([c.startswith("sh.688") for c in cols]); gem = np.array([c.startswith("sz.300") or c.startswith("sz.301") for c in cols])
        lim = np.where(star[None, :] | gem[None, :], 0.20, np.where(isst, 0.05, 0.10))
        O, PRE, CL = np.round(opn.to_numpy(), 2), np.round(pre.to_numpy(), 2), close.to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            aopen = O * adj / CL
        okk = (ts.to_numpy() == 1) & np.isfinite(O) & (O > 0)
        cs = okk & (O > r2(PRE * (1 - lim)) + 0.0005); cb = okk & (O < r2(PRE * (1 + lim)) - 0.0005)
        si = int(dates.searchsorted(pd.Timestamp(start)))
        nm = load.a_share_stocks().set_index("code").code_name.to_dict() if hasattr(load, "a_share_stocks") else {}
        for j, c in enumerate(cols):
            run_series(nm.get(c, c), c, dates, adj[:, j], aopen[:, j], O[:, j], cs[:, j], cb[:, j], elig[:, j], si, out_a)
    u = load.us_daily(ETFS, start=load_from)
    for t, x in u.groupby("ticker"):
        x = clean_etf(x.sort_values("date").set_index("date")); x = x[x.close > 0]
        if len(x) < 300: continue
        c = x.close.to_numpy(float); o = x.open.to_numpy(float); pre = np.r_[np.nan, c[:-1]]
        lim = 0.2 if t.startswith("588") else 0.1
        cs = np.isfinite(o) & (o > r3(pre * (1 - lim)) + 0.0005); cb = np.isfinite(o) & (o < r3(pre * (1 + lim)) - 0.0005)
        si = int(x.index.searchsorted(pd.Timestamp(start)))
        run_series(t, t, x.index, c, o, o, cs, cb, np.ones(len(c), bool), si, out_e)
    return out_a, out_e


def summary(E):
    if not E: return dict(n=0)
    D = pd.DataFrame(E); s = {"n": len(D), "closed": int(D.closed.sum())}
    for k, x in [("all", D), ("closed_only", D[D.closed])]:
        if len(x):
            s[k] = dict(n=len(x), hold=rn(x.hold.mean()), rule=rn(x.rule.mean()), fix94=rn(x.fix94.mean()),
                        rule_minus_hold=rn((x.rule - x.hold).mean()), rule_minus_fix94=rn((x.rule - x.fix94).mean()),
                        hold_mdd=rn(x.hold_mdd.mean()), rule_mdd=rn(x.rule_mdd.mean()), triggered=int((x.trades.map(len) > 0).sum()))
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--jsq", required=True); ap.add_argument("--site", required=True)
    ap.add_argument("--start", default=RULE["start"]); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    os.environ["MARKET_DATA"] = a.data; sys.path.insert(0, a.jsq)
    from market_data import load  # noqa: E402
    load_from = str((pd.Timestamp(a.start) - pd.Timedelta(days=900)).date())
    EA, EE = build(load, a.data, a.start, load_from)
    EA.sort(key=lambda e: (e["d"], e["code"])); EE.sort(key=lambda e: (e["d"], e["code"]))
    o = dict(rule=RULE, note=__doc__.strip().splitlines()[0], updated=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
             start=a.start, a_share=dict(summary=summary(EA), events=EA[-200:]), etf=dict(summary=summary(EE), events=EE[-100:]))
    out = a.out or os.path.join(a.site, "top_ledger.json")
    json.dump(o, open(out, "w"), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"top_ledger: A股科技池 {len(EA)} 个事件（结完 {o['a_share']['summary'].get('closed', 0)}），ETF {len(EE)} 个")
