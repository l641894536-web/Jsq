"""A股科技股：下降结构出现后离场，能少承受多少下跌、多遭遇多少次卖飞（只管退出；入场见 ashare_entry_bt.py）。2026-11-15 定稿后才跑。

股票池同 ashare_entry_bt（证监会 C39/I63/I64/I65；日均成交≥3000万、非ST、上市满250天）；美股不混入。
起点：每个月第一个交易日，池子里每只股票都当作"这天收盘时手里拿着"（资金1，和怎么买进来的无关，这样退出和入场分开）。
离场规则（收盘出信号 → 下一个能成交的开盘全部卖出，开盘在跌停价卖不出就顺延；卖了不再买回）：
  X1 跌破60日线且跌破前20个交易日最低收盘（上次那一种写法）
  X2 创20日新低：收盘低于前20个交易日最低收盘（低点下移）
  X3 均线转空：20日线在60日线下面，且收盘在20日线下面
  X4 从起点以来最高收盘回落15%
对照：一直拿到终点。终点 = 起点后第 H 个交易日（H = 20 / 60 / 120），第 H 天收盘发卖出指令 → 下一个能成交的开盘卖；卖出各扣0.15%。
看：
  ① 少承受多少下跌：资金曲线最大回撤（平均/最差一成）；触发离场的那些，卖出后到终点这只股票又跌了多少（躲过的跌幅）
  ② 卖飞：触发离场的那些，终点价格高于卖出价的比例、高出10%以上的比例、平均错过多少
  ③ 净收益比一直拿着多多少（月度序列 Newey-West / 移动块自助，取宽）
  ④ 分四段（按起点日期，2016-07→2018-12、2019-01→2021-10、2021-11→2023-12、2024-01→2026-05，每段最后 H+5 个交易日的起点丢掉），四段方向一致才算可重复。
这些数据以前都看过，不称样本外。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct
from ashare_top6_bt import prep, TECH
from ashare_entry_bt import BLOCKS, ci_overlap

COST = 0.0015
HS = (20, 60, 120)
RULES = ["X1 破60日线且破20日最低", "X2 创20日新低", "X3 均线转空", "X4 从最高回落15%"]


def run(W, X):
    adj, dates = W["adj"], W["dates"]; T = len(dates)
    tech = np.where(np.isin(W["ind"], list(TECH)))[0]
    A = pd.DataFrame(adj[:, tech])
    ma20 = A.rolling(20, min_periods=15).mean().to_numpy(); ma60 = A.rolling(60, min_periods=45).mean().to_numpy()
    lo20 = A.rolling(20, min_periods=15).min().shift(1).to_numpy()
    month_first = np.r_[True, dates[1:].month != dates[:-1].month]
    bidx = [(dates.searchsorted(pd.Timestamp(a)), dates.searchsorted(pd.Timestamp(b), side="right")) for a, b in BLOCKS]
    rows = []
    for jj, j in enumerate(tech):
        c = adj[:, j]; cs = X["can_sell"][:, j]; o = X["aopen"][:, j]; U = W["U"][:, j]
        sig = {RULES[0]: (c < ma60[:, jj]) & (c < lo20[:, jj]), RULES[1]: c < lo20[:, jj],
               RULES[2]: (ma20[:, jj] < ma60[:, jj]) & (c < ma20[:, jj])}
        sig = {k: np.where(np.nan_to_num(v, nan=0).astype(bool))[0] for k, v in sig.items()}
        okidx = np.where(cs)[0]
        for t0 in np.where(month_first & U)[0]:
            k = next((kk for kk, (a, b) in enumerate(bidx) if a <= t0 < b - 125), None)
            if k is None or t0 + 125 >= T or not np.isfinite(c[t0]): continue
            for H in HS:
                ex = t0 + H; p = np.searchsorted(okidx, ex + 1); sell_end = okidx[p] if p < len(okidx) else T - 1
                hold_v = o[sell_end] * (1 - COST) / c[t0] if np.isfinite(o[sell_end]) else c[-1] / c[t0]
                pathH = c[t0:sell_end] / c[t0]
                r = dict(d=dates[t0], blk=k, H=H, hold=hold_v - 1, hold_mdd=float(np.min(np.r_[pathH, hold_v] / np.maximum.accumulate(np.r_[pathH, hold_v]) - 1)))
                for rule in RULES:
                    if rule == RULES[3]:
                        run_max = np.maximum.accumulate(c[t0:ex]); hit = np.where(c[t0:ex] <= run_max * 0.85)[0]
                        s = t0 + hit[0] if len(hit) else None
                    else:
                        arr = sig[rule]; q = np.searchsorted(arr, t0 + 1); s = arr[q] if q < len(arr) and arr[q] <= ex - 1 else None
                    if s is None:
                        r[rule] = r["hold"]; r[rule + "|mdd"] = r["hold_mdd"]; r[rule + "|hit"] = False
                        continue
                    q = np.searchsorted(okidx, s + 1); sd = okidx[q] if q < len(okidx) else None
                    if sd is None or sd >= sell_end:      # 和终点同一天卖 = 没区别，按没触发算
                        r[rule] = r["hold"]; r[rule + "|mdd"] = r["hold_mdd"]; r[rule + "|hit"] = False; continue
                    v = o[sd] * (1 - COST) / c[t0]; path = np.r_[c[t0:sd] / c[t0], v]
                    r[rule] = v - 1; r[rule + "|mdd"] = float(np.min(path / np.maximum.accumulate(path) - 1)); r[rule + "|hit"] = True
                    r[rule + "|after_min"] = float(np.nanmin(np.r_[c[sd:sell_end], o[sell_end]]) / o[sd] - 1)       # 卖出后到终点又跌了多少
                    r[rule + "|after_end"] = float(hold_v * c[t0] / (1 - COST) / o[sd] - 1)     # 终点价比卖出价
                    r[rule + "|days"] = int(sd - t0)
                rows.append(r)
    return pd.DataFrame(rows)


def report(D):
    print(f"\n######## A股科技池：{(D.H == 20).sum():,} 个'月初手里拿着'的起点（各段 {D[D.H == 20].groupby('blk').size().to_dict()}）")
    for H in HS:
        X = D[D.H == H].copy()
        print(f"\n—— 观察 {H} 个交易日")
        out = [{"做法": "一直拿着", "平均": pct(X.hold.mean()), "中位": pct(X.hold.median()), "最差一成": pct(X.hold.quantile(.1)),
                "资金最大回撤(平均/最差一成)": f"{pct(X.hold_mdd.mean())}/{pct(X.hold_mdd.quantile(.1))}"}]
        out2 = []
        for rule in RULES:
            X["diff"] = X[rule] - X.hold; h = X[X[rule + "|hit"] == True]
            mu, lo, hi_, how = ci_overlap(X, "diff", L=max(2, H // 21 + 1))
            out.append({"做法": rule, "平均": pct(X[rule].mean()), "中位": pct(X[rule].median()), "最差一成": pct(X[rule].quantile(.1)),
                        "资金最大回撤(平均/最差一成)": f"{pct(X[rule + '|mdd'].mean())}/{pct(X[rule + '|mdd'].quantile(.1))}"})
            out2.append({"做法": rule, "触发离场": f"{X[rule + '|hit'].mean():.0%}", "平均第几天卖": f"{h[rule + '|days'].mean():.0f}" if len(h) else "—",
                         "卖后又跌(中位/最差一成)": f"{pct(h[rule + '|after_min'].median())}/{pct(h[rule + '|after_min'].quantile(.1))}" if len(h) else "—",
                         "卖飞:终点高于卖价": f"{(h[rule + '|after_end'] > 0).mean():.0%}" if len(h) else "—",
                         "其中高出10%+": f"{(h[rule + '|after_end'] > 0.1).mean():.0%}" if len(h) else "—",
                         "卖飞的平均错过": pct(h[rule + '|after_end'][h[rule + '|after_end'] > 0].mean()) if len(h) else "—",
                         "比拿着多赚": pct(X["diff"].mean()), "95%区间": f"{pct(lo)}~{pct(hi_)}" if np.isfinite(lo) else "—",
                         **{f"段{k + 1}": pct(X[X.blk == k]["diff"].mean()) for k in range(4)}})
        print(pd.DataFrame(out).to_string(index=False))
        print(pd.DataFrame(out2).to_string(index=False))
        print("  分段一直拿着本身：" + "，".join(f"段{k + 1} {pct(X[X.blk == k].hold.mean())}" for k in range(4)))


def static_compare(W, X, D):
    """对照：起点就只拿固定比例 w（= 这条离场规则在这个观察期里的平均持股比例，所有起点同一个 w，事前可定），其余现金，不再动。
    离场规则如果只是'少拿了'，它不会比这个对照好；要比这个对照收益高或回撤小，才说明离场时机本身有用。"""
    adj, dates = W["adj"], W["dates"]; T = len(dates)
    tech = np.where(np.isin(W["ind"], list(TECH)))[0]; month_first = np.r_[True, dates[1:].month != dates[:-1].month]
    bidx = [(dates.searchsorted(pd.Timestamp(a)), dates.searchsorted(pd.Timestamp(b), side="right")) for a, b in BLOCKS]
    wmap = {}
    for H in HS:
        x = D[D.H == H]
        wmap[H] = {r: float(np.where(x[r + "|hit"] == True, x[r + "|days"] / (H + 1), 1.0).mean()) for r in RULES}
    rows = []
    for j in tech:
        c = adj[:, j]; cs = X["can_sell"][:, j]; o = X["aopen"][:, j]; U = W["U"][:, j]; okidx = np.where(cs)[0]
        for t0 in np.where(month_first & U)[0]:
            k = next((kk for kk, (a, b) in enumerate(bidx) if a <= t0 < b - 125), None)
            if k is None or t0 + 125 >= T or not np.isfinite(c[t0]): continue
            for H in HS:
                ex = t0 + H; p = np.searchsorted(okidx, ex + 1); se = okidx[p] if p < len(okidx) else T - 1
                hv = o[se] * (1 - COST) / c[t0] if np.isfinite(o[se]) else c[-1] / c[t0]
                path = np.r_[c[t0:se] / c[t0], hv]
                r = dict(d=dates[t0], blk=k, H=H)
                for rule, w in wmap[H].items():
                    e = (1 - w) + w * path
                    r[rule + "|s_ret"] = e[-1] - 1; r[rule + "|s_mdd"] = float(np.min(e / np.maximum.accumulate(e) - 1))
                rows.append(r)
    S = pd.DataFrame(rows)
    for H in HS:
        x = D[D.H == H].reset_index(drop=True); s_ = S[S.H == H].reset_index(drop=True)
        assert len(x) == len(s_) and (x.d.values == s_.d.values).all()
        print(f"\n—— 观察 {H} 天：离场规则 vs 起点就只拿同样比例（固定 w）")
        out = []
        for rule in RULES:
            x["d2"] = x[rule] - s_[rule + "|s_ret"]
            mu, lo, hi_, how = ci_overlap(x, "d2", L=max(2, H // 21 + 1))
            out.append({"规则": rule, "w": f"{wmap[H][rule]:.0%}", "规则收益": pct(x[rule].mean()), "固定w收益": pct(s_[rule + "|s_ret"].mean()),
                        "规则−固定w": pct(x["d2"].mean()), "95%区间": f"{pct(lo)}~{pct(hi_)}" if np.isfinite(lo) else "—",
                        "回撤平均 规则/固定w": f"{pct(x[rule + '|mdd'].mean())}/{pct(s_[rule + '|s_mdd'].mean())}",
                        "回撤最差一成 规则/固定w": f"{pct(x[rule + '|mdd'].quantile(.1))}/{pct(s_[rule + '|s_mdd'].quantile(.1))}",
                        "最差一成收益 规则/固定w": f"{pct(x[rule].quantile(.1))}/{pct(s_[rule + '|s_ret'].quantile(.1))}",
                        **{f"段{k + 1}": pct(x[x.blk == k]["d2"].mean()) for k in range(4)}})
        print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__" and os.environ.get("STATIC"):
    os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, "/home/claude/jsq")
    W = world("2015-01-01"); X = prep(W); static_compare(W, X, pd.read_pickle("/tmp/_exit_stock.pkl")); sys.exit()
if __name__ == "__main__":
    os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, "/home/claude/jsq")
    W = world("2015-01-01"); X = prep(W)
    D = run(W, X); D.to_pickle("/tmp/_exit_stock.pkl"); report(D)
