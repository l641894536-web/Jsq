"""A股科技股"跌了要不要买、什么时候买"：入场方式检验（只管入场；退出统一，另做）。2026-11-15 定稿后才跑，跑完不改参数。

股票池（固定，同 ashare_top6_bt）：证监会行业 C39（计算机、通信和其他电子设备制造）+ I63（电信）+ I64（互联网）+ I65（软件和信息技术服务）。
  个股要求：日均成交（20日）≥3000万、非ST、上市满250个交易日。ETF 另算（etf_part），美股不混入。
起点（"跌出机会"，参数来自之前的研究，没有为这次调）：第一次收盘跌到一年高点（250日）70%以下，且之前60个交易日都在75%以上；同一只冷却60个交易日。
入场方式（收盘出信号 → 下一个能成交的开盘买；开盘在涨停价买不进、停牌，都顺延）：
  A 立即买：起点当天收盘就算信号
  B 第一波反弹：收盘 ≥ 起点以来最低收盘 × 1.15
  C 反转确认：收盘 ≥ 起点以来最低收盘 × 1.3
  D 回踩确认：B 之后，从反弹最高收盘回落 ≥8% 且没跌破最低，再收盘超过反弹最高；中途跌破最低就从新低重新等
  E 站上60日线：收盘 > 60日均线
  F 60日新高：收盘 ≥ 前60个交易日最高收盘
统一口径（同一资金、同一终点）：每个起点资金1；观察期 H = 20 / 60 / 120 个交易日，从起点起算。
  入场信号只看起点到第 H−1 天的收盘；第 H 天收盘发卖出指令 → 下一个能成交的开盘卖（开盘在跌停价卖不出，顺延）。
  没等到入场就一直拿现金（收益0）——没等到确认而错过的上涨，就这样算进比较；买卖各扣0.15%。
看四件事：
  ① 危险：入场后到终点之间最深再跌多少（入场价起算）、终点收益最差一成、资金曲线最大回撤
  ② 确认的代价：入场价比"立即买"贵多少；有多少起点到终点都没等到入场；没等到的那些，立即买赚了多少（错过的上涨 / 躲过的下跌），
     以及"立即买的全部上涨里有百分之几被错过"
  ③ 扣成本后比"立即买"多赚多少：按起点月份平均成月度序列，Newey-West（滞后=H换算成月数+1）和同长度移动块自助法，取更宽的95%区间
  ④ 能不能重复：按起点日期分四段 2016-07→2018-12、2019-01→2021-10、2021-11→2023-12、2024-01→2026-05，
     每段最后 H+5 个交易日内的起点丢掉（持有期不跨段）；四段方向一致才算可重复。
     这些数据以前都被反复看过（起点定义、15%/30%/8% 都是在它们上面定的），所以四段都不算"没见过的样本"；真正的样本外只有以后的数据。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct
from ashare_top6_bt import prep, TECH, clean_etf, r3

COST = 0.0015
HS = (20, 60, 120)
METHODS = ["A 立即买", "B 第一波反弹", "C 反转确认", "D 回踩确认", "E 站上60日线", "F 60日新高"]
BLOCKS = [("2016-07-01", "2018-12-31"), ("2019-01-01", "2021-10-31"), ("2021-11-01", "2023-12-31"), ("2024-01-01", "2026-05-31")]


def setups(adj, elig, dates, blocks=BLOCKS, cool=60, tail=125):
    """返回 (t0, 段号)；冷却从整个序列算；每段最后 tail 个交易日内的起点丢掉。"""
    T = len(adj); hi = pd.Series(adj).rolling(250, min_periods=200).max().to_numpy(); r = adj / hi
    bidx = [(dates.searchsorted(pd.Timestamp(a)), dates.searchsorted(pd.Timestamp(b), side="right")) for a, b in blocks]
    out = []; last = -999
    for t in range(260, T):
        if not (elig[t] and np.isfinite(r[t]) and r[t] <= 0.70 and np.nanmax(r[t - 60:t]) >= 0.75 and t - last > cool):
            continue
        last = t
        for k, (a, b) in enumerate(bidx):
            if a <= t < b - tail and t + tail < T:
                out.append((t, k)); break
    return out


def signal_days(c, ma60, t0, horizon):
    """各入场方式第一次出信号的那天（收盘），只看 t0..t0+horizon-1；没有就 None。"""
    end = min(t0 + horizon - 1, len(c) - 1)
    sig = {"A 立即买": t0}
    L = c[t0]; b = c_ = d_ = e_ = f_ = None
    bh = None; pulled = False
    for t in range(t0 + 1, end + 1):
        x = c[t]
        if not np.isfinite(x): continue
        if x < L:
            L = x; bh = None; pulled = False           # 新低：回踩确认从头等
        if b is None and x >= L * 1.15: b = t
        if c_ is None and x >= L * 1.3: c_ = t
        if d_ is None:
            if bh is None:
                if x >= L * 1.15: bh = x
            else:
                if not pulled:
                    bh = max(bh, x)
                    if x <= bh * 0.92: pulled = True
                elif x > bh: d_ = t
        if e_ is None and np.isfinite(ma60[t]) and x > ma60[t]: e_ = t
        if f_ is None and x >= np.nanmax(c[t - 60:t]): f_ = t
    sig.update({"B 第一波反弹": b, "C 反转确认": c_, "D 回踩确认": d_, "E 站上60日线": e_, "F 60日新高": f_})
    return sig


def next_ok(ok, t, lim):
    for u in range(t + 1, min(lim, len(ok) - 1) + 1):
        if ok[u]: return u
    return None


def evaluate(c, o, cs, cb, ma60, t0, H):
    """一个起点、一个观察期：各方式的结果。"""
    T = len(c); sig = signal_days(c, ma60, t0, H)
    ex_sig = t0 + H                                     # 第 H 天收盘发卖出指令
    sell = next_ok(cs, ex_sig, T - 1)
    if sell is None: sell = None
    res = {}
    for m, s in sig.items():
        r = dict(entered=False, ret=0.0, mae=np.nan, px=np.nan, mdd=0.0, delay=np.nan)
        if s is not None:
            bd = next_ok(cb, s, ex_sig)                 # 最晚第 H 天开盘买进
            if bd is not None:
                sh = (1 - COST) / o[bd]
                if sell is not None:
                    val_end = sh * o[sell] * (1 - COST); last = sell
                else:
                    val_end = sh * c[-1]; last = T - 1
                path = np.r_[np.ones(bd - t0), sh * c[bd:last], val_end]
                r.update(entered=True, ret=val_end - 1, px=o[bd], delay=bd - t0,
                         mae=float(np.nanmin(c[bd:ex_sig + 1]) / o[bd] - 1),
                         mdd=float(np.min(path / np.maximum.accumulate(path) - 1)))
        res[m] = r
    return res


def run_pool(series, lab, show_blocks=True):
    """series: [(name, dates, c, o, cs, cb, elig)]"""
    rows = []
    for name, dates, c, o, cs, cb, elig in series:
        ma60 = pd.Series(c).rolling(60, min_periods=45).mean().to_numpy()
        for t0, k in setups(c, elig, dates):
            for H in HS:
                R = evaluate(c, o, cs, cb, ma60, t0, H)
                a = R["A 立即买"]
                for m, r in R.items():
                    rows.append(dict(name=name, d=dates[t0], blk=k, H=H, m=m, a_ret=a["ret"], a_px=a["px"], **r))
    D = pd.DataFrame(rows)
    if not len(D):
        print(f"\n######## {lab}：没有起点"); return D
    D["d"] = pd.to_datetime(D.d); D["diff"] = D.ret - D.a_ret; D["paid"] = D.px / D.a_px - 1
    n0 = D[(D.H == 20) & (D.m == "A 立即买")]
    print(f"\n######## {lab}：{len(n0):,} 个起点（{D.name.nunique()} 只；各段 {n0.groupby('blk').size().to_dict()}）")
    for H in HS:
        X = D[D.H == H]
        print(f"\n—— 观察 {H} 个交易日（起点起算，同一终点）")
        out = []
        aup = X[X.m == "A 立即买"].a_ret.clip(lower=0).sum()
        for m in METHODS:
            x = X[X.m == m]; e = x[x.entered]; ne = x[~x.entered]
            mu, lo, hi_, how = ci_overlap(x, "diff", L=max(2, H // 21 + 1)) if m != "A 立即买" else (0, 0, 0, "")
            row = {"方式": m, "入场率": f"{x.entered.mean():.0%}", "平均": pct(x.ret.mean()), "中位": pct(x.ret.median()),
                   "最差一成": pct(x.ret.quantile(.1)), "入场后最深再跌(中位/最差一成)": f"{pct(e.mae.median())}/{pct(e.mae.quantile(.1))}" if len(e) else "—",
                   "资金最大回撤(平均/最差一成)": f"{pct(x.mdd.mean())}/{pct(x.mdd.quantile(.1))}",
                   "比立即买贵": pct(e.paid.median()) if m != "A 立即买" and len(e) else "—",
                   "比立即买多赚": pct(x["diff"].mean()) if m != "A 立即买" else "—",
                   "95%区间": f"{pct(lo)}~{pct(hi_)}" if m != "A 立即买" and np.isfinite(lo) else "—"}
            if m != "A 立即买":
                row["没等到:立即买平均"] = pct(ne.a_ret.mean()) if len(ne) else "—"
                row["没等到里 大涨>20%/大跌<-10%"] = f"{(ne.a_ret > 0.2).mean():.0%}/{(ne.a_ret < -0.1).mean():.0%}" if len(ne) else "—"
                row["错过立即买全部上涨的"] = f"{ne.a_ret.clip(lower=0).sum() / aup:.0%}" if aup > 0 else "—"
            out.append(row)
        T1 = pd.DataFrame(out)
        print(T1[["方式", "入场率", "平均", "中位", "最差一成", "入场后最深再跌(中位/最差一成)", "资金最大回撤(平均/最差一成)"]].to_string(index=False))
        print(T1[["方式", "比立即买贵", "比立即买多赚", "95%区间", "没等到:立即买平均", "没等到里 大涨>20%/大跌<-10%", "错过立即买全部上涨的"]].fillna("—").to_string(index=False))
        if show_blocks:
            B = X[X.m != "A 立即买"].groupby(["m", "blk"])["diff"].mean().unstack()
            A = X[X.m == "A 立即买"].groupby("blk").ret.mean()
            print("  分段（比立即买多赚；最后一行是立即买本身的平均）：")
            B.columns = [f"段{k+1} {BLOCKS[k][0][:7]}" for k in B.columns]
            B.loc["(立即买本身)"] = A.values
            print(B.map(pct).to_string())
    return D


def ci_overlap(D, col, L=3, B=2000, seed=11):
    s = D.groupby(D.d.dt.to_period("M"))[col].mean(); x = s.to_numpy(float); n = len(x); mu = x.mean()
    if n < 3 * L: return mu, np.nan, np.nan, "月份太少"
    e = x - mu; nw = e @ e / n
    for l in range(1, L + 1): nw += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / n
    se = np.sqrt(max(nw, 0) / n); a1, b1 = mu - 1.96 * se, mu + 1.96 * se
    rng = np.random.default_rng(seed); nb = int(np.ceil(n / L)); bs = np.empty(B)
    for k in range(B):
        st = rng.integers(0, n, nb); ii = (st[:, None] + np.arange(L)[None, :]).ravel() % n; bs[k] = x[ii[:n]].mean()
    a2, b2 = np.percentile(bs, [2.5, 97.5])
    return (mu, a1, b1, "NW") if (b1 - a1) >= (b2 - a2) else (mu, a2, b2, "块自助")


def stock_series(W, X):
    adj = W["adj"]; dates = W["dates"]; out = []
    tech = np.isin(W["ind"], list(TECH))
    for j in np.where(tech)[0]:
        out.append((W["codes"][j], dates, adj[:, j], X["aopen"][:, j], X["can_sell"][:, j], X["can_buy"][:, j], W["U"][:, j]))
    return out


def etf_series():
    from market_data import load
    tks = ["512760.SS", "512480.SS", "588000.SS", "159995.SZ", "159801.SZ", "515050.SS", "515880.SS", "512720.SS",
           "515000.SS", "159939.SZ", "515980.SS", "159819.SZ", "512330.SS", "159807.SZ", "512980.SS"]
    d = load.us_daily(tks, start="2015-01-01"); out = []
    for t, x in d.groupby("ticker"):
        x = clean_etf(x.sort_values("date").set_index("date")); x = x[x.close > 0]
        c = x.close.to_numpy(float); o = x.open.to_numpy(float); pre = np.r_[np.nan, c[:-1]]; lim = 0.2 if t.startswith("588") else 0.1
        cs = np.isfinite(o) & (o > r3(pre * (1 - lim)) + 0.0005); cb = np.isfinite(o) & (o < r3(pre * (1 + lim)) - 0.0005)
        out.append((t, x.index, c, o, cs, cb, np.ones(len(c), bool)))
    return out


def static_compare(series, D, lab):
    """对照：起点后就按"立即买"的方式买，但只买固定比例 w（= 这种入场方式在这个观察期里的平均持股比例，所有起点同一个 w），其余现金。
    确认式入场如果只是'少拿了'，不会比这个对照好。"""
    W_ = {}
    for H in HS:
        x = D[D.H == H]
        W_[H] = {m: float(np.where(x[x.m == m].entered, 1 - x[x.m == m].delay / (H + 1), 0.0).mean()) for m in METHODS if m != "A 立即买"}
    rows = []
    for name, dates, c, o, cs, cb, elig in series:
        ma60 = pd.Series(c).rolling(60, min_periods=45).mean().to_numpy(); T = len(c)
        for t0, k in setups(c, elig, dates):
            for H in HS:
                ex = t0 + H; bd = next_ok(cb, t0, ex); sell = next_ok(cs, ex, T - 1)
                if bd is None: continue
                sh = (1 - COST) / o[bd]
                ve = sh * o[sell] * (1 - COST) if sell is not None else sh * c[-1]; last = sell if sell is not None else T - 1
                path = np.r_[np.ones(bd - t0), sh * c[bd:last], ve]
                r = dict(name=name, d=dates[t0], blk=k, H=H)
                for m, w in W_[H].items():
                    e = (1 - w) + w * path; r[m + "|s_ret"] = e[-1] - 1; r[m + "|s_mdd"] = float(np.min(e / np.maximum.accumulate(e) - 1))
                rows.append(r)
    S = pd.DataFrame(rows); S["d"] = pd.to_datetime(S.d)
    print(f"\n######## {lab}：确认式入场 vs 立即买但只买同样比例（固定 w）")
    for H in HS:
        out = []
        for m, w in W_[H].items():
            x = D[(D.H == H) & (D.m == m)][["name", "d", "blk", "ret", "mdd"]].merge(S[S.H == H][["name", "d", m + "|s_ret", m + "|s_mdd"]], on=["name", "d"])
            x["d2"] = x.ret - x[m + "|s_ret"]
            mu, lo, hi_, how = ci_overlap(x, "d2", L=max(2, H // 21 + 1))
            out.append({"H": H, "方式": m, "w": f"{w:.0%}", "方式收益": pct(x.ret.mean()), "固定w收益": pct(x[m + "|s_ret"].mean()),
                        "方式−固定w": pct(x.d2.mean()), "95%区间": f"{pct(lo)}~{pct(hi_)}" if np.isfinite(lo) else "—",
                        "回撤平均 方式/固定w": f"{pct(x.mdd.mean())}/{pct(x[m + '|s_mdd'].mean())}",
                        "回撤最差一成 方式/固定w": f"{pct(x.mdd.quantile(.1))}/{pct(x[m + '|s_mdd'].quantile(.1))}",
                        "最差一成收益 方式/固定w": f"{pct(x.ret.quantile(.1))}/{pct(x[m + '|s_ret'].quantile(.1))}",
                        **{f"段{k + 1}": pct(x[x.blk == k].d2.mean()) for k in sorted(x.blk.unique())}})
        print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__" and os.environ.get("STATIC"):
    os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, "/home/claude/jsq")
    W = world("2015-01-01"); X = prep(W)
    static_compare(stock_series(W, X), pd.read_pickle("/tmp/_entry_stock.pkl"), "A股科技池"); sys.exit()
if __name__ == "__main__":
    os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, "/home/claude/jsq")
    if os.environ.get("WHICH") == "etf":
        D = run_pool(etf_series(), "科技类ETF（15只，Yahoo日线清洗）", show_blocks=True)
        D.to_pickle("/tmp/_entry_etf.pkl")
    else:
        W = world("2015-01-01"); X = prep(W)
        D = run_pool(stock_series(W, X), "A股科技池（C39/I63/I64/I65）")
        D.to_pickle("/tmp/_entry_stock.pkl")
