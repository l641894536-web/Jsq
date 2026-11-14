"""A股被套之后（离一年高点跌30%）：①大盘拿哪个当参照最好 ②反弹还是反转，能不能提前认出来 ③高抛低吸能不能比一直拿着赚得多。
事件同 research/holder_bt.py：日均成交≥3000万、非ST、上市满250天；第一次跌到一年高点70%以下（之前60天还在75%以上），冷却60天；
起点 2021-11-01 → 2025-10（要有之后250个交易日），前后两段以 2024-05-15 为界。所有判断只用当天收盘能知道的数。
第一部分（参照）：全A等权 / 沪深300 / 中证500 / 中证1000 / 创业板指 / 上证指数 / 它所在行业（证监会行业大类等权）
  "好状态" = 参照在200日线下（大家一起跌）且它60天没比参照多跌20%；看死扛、越跌越加的平均和最差10%、之后再跌20%的比例。
第二部分（反弹 vs 反转）：L = 起点之后的最低收盘；第一波反弹 E1 = 第一次收盘 ≥ L×1.15。
  之后120天里先涨到 L×1.5 = 反转；先跌破 L = 反弹失败。看 E1 当天的各种特征能不能分开两者（前后两段方向要一致才算）。
  另看几种常见"反转确认"信号（站上半年线、60日新高、20日线上穿60日线、从低点涨30%、二次确认）出现之后的表现。
"""
import os, sys, pickle
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
import apanel

START, MID, H = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-15"), 250
CACHE = "/tmp/_swing_world_{}.pkl"
pct = lambda v: "—" if v is None or not np.isfinite(v) else f"{v*100:+.1f}%"


def world(frm="2019-06-01"):
    if os.path.exists(CACHE.format(frm)):
        return pickle.load(open(CACHE.format(frm), "rb"))
    P = apanel.build(extra=True); D = apanel.derive(P)
    dates = D["dates"]; t0 = dates.searchsorted(pd.Timestamp(frm))
    sl = lambda M: np.ascontiguousarray(M[t0:])
    dates = dates[t0:]; codes = D["codes"]
    adj = pd.DataFrame(sl(D["adj"])).ffill().to_numpy()
    traded = sl(D["traded"]); st = sl(D["st"]); age = sl(D["age"]); ok = sl(D["ok"])
    amt = np.where(traded, sl(P["amount"]).astype("float64"), np.nan)
    am20 = pd.DataFrame(amt).rolling(20, min_periods=10).mean().to_numpy()
    U = traded & ~st & (age >= 250) & (am20 >= 3e7)
    s = D["s"].iloc[t0:].copy()
    s["prev5"] = s["温度"].shift(1).rolling(5).mean()
    zt = sl(D["zt"])
    # 指数
    ix = pd.read_csv(f"{os.environ['MARKET_DATA']}/a_share/index_daily.csv.xz", dtype={"code": str}, parse_dates=["date"])
    ix["close"] = ix.close.astype(float)
    ref = {"全A等权": s["等权指数"].to_numpy(float)}
    for c, nm in [("sh.000300", "沪深300"), ("sh.000905", "中证500"), ("sh.000852", "中证1000"), ("sz.399006", "创业板指"), ("sh.000001", "上证指数")]:
        ref[nm] = ix[ix.code == c].set_index("date").close.reindex(dates).ffill().to_numpy(float)
    # 行业等权（证监会行业大类，例如 C39 电子设备；成员少于15只的用全A等权）
    im = pd.read_csv(f"{os.environ['MARKET_DATA']}/a_share/meta/industry.csv", dtype=str).set_index("code").industry.str.slice(0, 3)
    ind = np.array([im.get(c, "") if isinstance(im.get(c, ""), str) else "" for c in codes], dtype=object)
    pr = np.where(ok & (age >= 60), sl(D["pct"]) / 100, np.nan)
    ind_ix = {}
    for k in sorted(set(ind)):
        m = ind == k
        if k and m.sum() >= 15:
            ind_ix[k] = np.cumprod(1 + np.nan_to_num(np.nanmean(pr[:, m], 1)))
    W = dict(dates=dates, codes=codes, adj=adj, amt=amt, U=U, s=s, zt=zt, ref=ref, ind=ind, ind_ix=ind_ix,
             high=sl(P["high"]).astype("float64"), close=sl(P["close"]).astype("float64"))
    pickle.dump(W, open(CACHE.format(frm), "wb"), protocol=4)
    return W


def growth_at(W):
    """每个(日, 股票) 最近一期已公告的归母净利润同比（YOYPNI），按月取样够用：返回函数 g(i, j)。"""
    g = pd.read_csv("/home/claude/fund/a_share/growth.csv.xz", dtype={"code": str}, parse_dates=["pubDate", "statDate"])
    g = g[g.pubDate.notna()].sort_values("pubDate")
    by = {c: (x.pubDate.to_numpy(), x.YOYPNI.to_numpy(float)) for c, x in g.groupby("code")}
    dates, codes = W["dates"], W["codes"]
    def f(i, j):
        v = by.get(codes[j])
        if v is None: return np.nan
        k = np.searchsorted(v[0], np.datetime64(dates[i]), side="right") - 1
        return v[1][k] if k >= 0 else np.nan
    return f


def events(W, start=START, until=None):
    dates, adj, U, s = W["dates"], W["adj"], W["U"], W["s"]
    T, N = adj.shape
    hi = pd.DataFrame(adj).rolling(250, min_periods=200).max().to_numpy()
    ma60 = pd.DataFrame(adj).rolling(60, min_periods=45).mean().to_numpy()
    ma120 = pd.DataFrame(adj).rolling(120, min_periods=90).mean().to_numpy()
    ma20 = pd.DataFrame(adj).rolling(20, min_periods=15).mean().to_numpy()
    a5 = pd.DataFrame(W["amt"]).rolling(5, min_periods=3).mean().to_numpy()
    a60 = pd.DataFrame(W["amt"]).rolling(60, min_periods=40).mean().to_numpy()
    ew = W["ref"]["全A等权"]; temp = s["温度"].to_numpy(float); p5 = s["prev5"].to_numpy(float)
    refs = W["ref"]; rma = {k: pd.Series(v).rolling(200, min_periods=150).mean().to_numpy() for k, v in refs.items()}
    ind_ix = W["ind_ix"]; ima = {k: pd.Series(v).rolling(200, min_periods=150).mean().to_numpy() for k, v in ind_ix.items()}
    ima20 = {k: pd.Series(v).rolling(20).mean().to_numpy() for k, v in ind_ix.items()}
    gr = growth_at(W)
    t0 = dates.searchsorted(start); t1 = dates.searchsorted(until, side="right") if until is not None else T
    rows = []
    for j in range(N):
        c = adj[:, j]; ratio = c / hi[:, j]; last = -999
        ik = W["ind"][j] if W["ind"][j] in ind_ix else None
        i = max(t0, 260)
        while i < min(T - H, t1):
            if not (U[i, j] and ratio[i] <= 0.70 and np.nanmax(ratio[i - 60:i]) >= 0.75 and i - last > 60):
                i += 1; continue
            last = i; p0 = c[i]; end = i + H
            r = dict(i=i, j=j, d=dates[i], ind=W["ind"][j])
            # 结果：死扛、越跌越加、之后再跌20%
            r["hold"] = c[end] / p0 - 1; r["mdd"] = np.nanmin(c[i:end + 1]) / p0 - 1
            pnl = r["hold"]
            for lvl in (0.9, 0.8):
                hit = np.where(c[i + 1:end + 1] <= p0 * lvl)[0]
                if len(hit): pnl += c[end] / c[i + 1 + hit[0]] - 1
            r["addp"] = pnl; r["mkt"] = ew[end] / ew[i] - 1
            # 第一部分：各参照
            for k, v in list(refs.items()) + [("行业", ind_ix[ik] if ik else ew)]:
                ma = (ima[ik] if ik else rma["全A等权"]) if k == "行业" else rma[k]
                r["dn_" + k] = v[i] < ma[i]
                r["rel_" + k] = (c[i] / c[i - 60] - 1) - (v[i] / v[i - 60] - 1)
            # 第二部分：第一波反弹
            L = p0; tL = i; E1 = None
            for t in range(i + 1, end + 1):
                if c[t] < L: L = c[t]; tL = t
                elif c[t] >= L * 1.15: E1 = t; break
            r["E1"] = E1
            if E1 is not None and E1 + 120 < T:
                w = c[E1 + 1:E1 + 121]
                brk = np.where(w < L)[0]; up = np.where(w >= L * 1.5)[0]
                b0 = brk[0] if len(brk) else 999; u0 = up[0] if len(up) else 999
                r["rev"] = u0 < b0; r["fail"] = b0 < u0 and b0 < 999
                r["f60"] = c[E1 + 60] / c[E1] - 1 - (ew[E1 + 60] / ew[E1] - 1); r["f120"] = c[E1 + 120] / c[E1] - 1
                r["L"] = L; r["tL"] = tL
                r["x_vol"] = a5[E1, j] / a60[tL, j] if np.isfinite(a60[tL, j]) and a60[tL, j] > 0 else np.nan
                r["x_days"] = E1 - tL
                r["x_ma60"] = c[E1] > ma60[E1, j]; r["x_ma120"] = c[E1] > ma120[E1, j]
                r["x_ma60up"] = ma60[E1, j] > ma60[E1 - 10, j]
                r["x_relb"] = (c[E1] / L - 1) - (ew[E1] / ew[tL] - 1)
                r["x_ind20"] = (ind_ix[ik][E1] > ima20[ik][E1]) if ik else np.nan
                r["x_indb"] = (ind_ix[ik][E1] / ind_ix[ik][tL] - 1) if ik else np.nan
                r["x_mktdn"] = ew[E1] < rma["全A等权"][E1]
                r["x_temp"] = temp[E1]; r["x_tup"] = temp[E1] > p5[E1]
                r["x_zt"] = bool(W["zt"][tL:E1 + 1, j].any())
                r["x_depth"] = L / hi[tL, j] - 1
                r["x_gr"] = gr(E1, j)
            # 反转确认信号：起点之后第一次出现（要在 L 之后）
            for nm, cond in [("半年线", lambda t: c[t] > ma120[t, j]), ("60日新高", lambda t: c[t] >= np.nanmax(c[t - 60:t])),
                             ("20上穿60", lambda t: ma20[t, j] > ma60[t, j] and ma20[t - 1, j] <= ma60[t - 1, j]),
                             ("涨30%", None)]:
                Lr = p0; s_ = None
                for t in range(i + 1, end + 1):
                    if c[t] < Lr: Lr = c[t]; continue
                    if (c[t] >= Lr * 1.3) if cond is None else (t > i + 5 and cond(t)):
                        s_ = t; break
                if s_ is not None and s_ + 120 < T:
                    w = c[s_ + 1:s_ + 121]
                    r["s_" + nm] = True; r["sb_" + nm] = bool((w < Lr).any())
                    r["sf_" + nm] = c[s_ + 120] / c[s_] - 1 - (ew[s_ + 120] / ew[s_] - 1)
                    r["sd_" + nm] = np.nanmin(w) / c[s_] - 1
                else:
                    r["s_" + nm] = False
            rows.append(r)
            i += 60
    R = pd.DataFrame(rows)
    R["per"] = np.where(R.d < MID, "前半", "后半")
    return R


def part1(R):
    print("\n==== 第一部分：大盘用哪个当参照（好状态 = 参照在200日线下 且 它60天没比参照多跌20%）")
    out = []
    for k in ["全A等权", "沪深300", "中证500", "中证1000", "创业板指", "上证指数", "行业"]:
        g = R["dn_" + k] & (R["rel_" + k] > -0.2); b = ~g
        x, y = R[g], R[b]
        q = lambda z, col, p: z[col].quantile(p)
        out.append({"参照": k, "好状态占比": f"{g.mean():.0%}", "好:死扛": pct(x.hold.mean()), "坏:死扛": pct(y.hold.mean()),
                    "好:再跌20%+": f"{(x.mdd<=-0.2).mean():.0%}", "坏:再跌20%+": f"{(y.mdd<=-0.2).mean():.0%}",
                    "好:加仓最差10%": pct(q(x, "addp", .1)), "坏:加仓最差10%": pct(q(y, "addp", .1)),
                    "前半 好/坏 加仓最差10%": f"{pct(q(x[x.per=='前半'],'addp',.1))}/{pct(q(y[y.per=='前半'],'addp',.1))}",
                    "后半 好/坏": f"{pct(q(x[x.per=='后半'],'addp',.1))}/{pct(q(y[y.per=='后半'],'addp',.1))}",
                    "前半 好/坏 死扛": f"{pct(x[x.per=='前半'].hold.mean())}/{pct(y[y.per=='前半'].hold.mean())}"})
    print(pd.DataFrame(out).to_string(index=False))
    # 只看"它自己比参照多跌"这一项，哪个参照分得最开
    out = []
    for k in ["全A等权", "沪深300", "中证1000", "创业板指", "行业"]:
        for lo, hi_, nm in [(-9, -0.2, "多跌20%+"), (-0.2, 0, "多跌0~20%"), (0, 9, "比参照强")]:
            m = (R["rel_" + k] > lo) & (R["rel_" + k] <= hi_); x = R[m]
            out.append({"参照": k, "60天相对": nm, "次数": len(x), "死扛": pct(x.hold.mean()), "再跌20%+": f"{(x.mdd<=-0.2).mean():.0%}",
                        "加仓最差10%": pct(x.addp.quantile(.1)), "前半死扛": pct(x[x.per == '前半'].hold.mean()), "后半死扛": pct(x[x.per == '后半'].hold.mean())})
    print(pd.DataFrame(out).to_string(index=False))


def part2(R):
    B = R[R.E1.notna() & R["rev"].notna()].copy()
    B["rev"] = B.rev.astype(float); B["fail"] = B.fail.astype(float)
    for c in [c for c in R.columns if c.startswith("sb_")]: R[c] = R[c].astype(float)
    print(f"\n==== 第二部分：第一波反弹（从低点涨15%）之后120天：反转（先到低点×1.5）{B.rev.mean():.0%}，失败（先破低点）{B.fail.mean():.0%}，共 {len(B):,} 次")
    feats = [("放量(5日额/低点时60日额≥1.5)", B.x_vol >= 1.5), ("反弹快(≤10天)", B.x_days <= 10), ("站上60日线", B.x_ma60), ("站上半年线", B.x_ma120),
             ("60日线已拐头向上", B.x_ma60up), ("反弹比大盘多涨10%+", B.x_relb >= 0.10), ("行业站上20日线", B.x_ind20 == True),
             ("行业从低点涨5%+", B.x_indb >= 0.05), ("大盘在200日线下", B.x_mktdn), ("情绪温度≥50", B.x_temp >= 50), ("情绪在升温", B.x_tup),
             ("反弹里有涨停", B.x_zt), ("跌得深(低点<高点×0.55)", B.x_depth <= -0.45), ("净利润同比为正", B.x_gr > 0)]
    out = []
    for nm, m in feats:
        m = m.fillna(False).astype(bool)
        row = {"E1当天": nm, "占比": f"{m.mean():.0%}"}
        for per in ["前半", "后半"]:
            x, y = B[m & (B.per == per)], B[~m & (B.per == per)]
            row[per + " 反转 有/无"] = f"{x.rev.mean():.0%}/{y.rev.mean():.0%}"
            row[per + " 失败 有/无"] = f"{x.fail.mean():.0%}/{y.fail.mean():.0%}"
            row[per + " 60天比大盘"] = f"{pct(x.f60.mean())}/{pct(y.f60.mean())}"
        out.append(row)
    print(pd.DataFrame(out).to_string(index=False))
    print("\n---- 反转确认信号（起点后第一次出现）：之后120天 破前低的比例、比大盘、最深再跌")
    out = []
    base = B
    out.append({"信号": "第一波反弹(涨15%)", "出现": f"{len(base)/len(R):.0%}", "之后破低点": f"{base.fail.mean():.0%}", "120天比大盘": "—",
                "前半破/后半破": f"{base[base.per=='前半'].fail.mean():.0%}/{base[base.per=='后半'].fail.mean():.0%}"})
    for nm in ["涨30%", "半年线", "60日新高", "20上穿60"]:
        x = R[R["s_" + nm] == True]
        out.append({"信号": nm, "出现": f"{len(x)/len(R):.0%}", "之后破低点": f"{x['sb_'+nm].mean():.0%}", "120天比大盘": pct(x["sf_" + nm].mean()),
                    "最深再跌(中位)": pct(x["sd_" + nm].median()),
                    "前半破/后半破": f"{x[x.per=='前半']['sb_'+nm].mean():.0%}/{x[x.per=='后半']['sb_'+nm].mean():.0%}",
                    "前半/后半 比大盘": f"{pct(x[x.per=='前半']['sf_'+nm].mean())}/{pct(x[x.per=='后半']['sf_'+nm].mean())}"})
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__" and os.environ.get("ONLY2"):
    part2(pd.read_pickle("/tmp/_swing_events.pkl")); sys.exit()
if __name__ == "__main__":
    W = world()
    R = events(W)
    R.to_pickle("/tmp/_swing_events.pkl")
    print(f"事件 {len(R):,}（{R.d.min().date()} → {R.d.max().date()}）")
    part1(R)
    part2(R)
