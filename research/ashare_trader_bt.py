"""A股交易者常用做法回测（日线近似；手续费+滑点来回按 0.3% 扣，ETF/指数按 0.05%）。
近5年 2021-11 → 2026-11 为主（前半 2021-11~2024-05，后半 2024-05~），2016-2021 对照；牛熊按全A等权200日线；短线类再按情绪阶段分。
做法：
  打板（首板/连板接力）：当天冲到涨停价就按涨停价买（三种成交假设：都能买到 / 只买到后来炸板的 / 只买到封住的），第二天开盘或收盘卖
  涨停次日开盘追：今天首板封住，明天开盘买，后天收盘卖
  涨停回马枪：首板后2~10天回落到涨停日收盘价95%以下、没破涨停日最低价，收盘买，拿5天
  缩量回踩20日线：20日线在60日线上、60日线向上，收盘在20日线 −2%~+1%，成交额不到20日均额70%，收盘买，拿10天
  超跌反弹：5天跌15%以上（当天没跌停），收盘买，拿5天
  净利润断层：财报净利润同比≥100%、市盈率为正，公告后第一个交易日高开≥2%且收在开盘价上方，当天收盘买，拿20/60天
  隔夜持股：收盘买、第二天开盘卖
  节前效应：春节/国庆长假前5个交易日买、节后第2天收盘卖
  二八轮动：每周五比沪深300和中证1000的20日涨幅，拿强的；两个都跌就空仓
  均线择时：中证1000 收在20日线上方就拿，下方空仓
  行业轮动：每周五按20日涨幅挑最强3个行业（行业内等权），拿一周
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
import apanel
from market_data import load

P = apanel.build(extra=True)
dates = pd.to_datetime(P["dates"]); codes = P["codes"].astype(str); T, N = P["close"].shape
traded = (np.nan_to_num(P["tradestatus"]) == 1) & np.isfinite(P["close"]) & (np.nan_to_num(P["amount"]) > 0)
st = np.nan_to_num(P["isST"]).astype(bool); age = np.cumsum(traded, axis=0)
ok = traded & ~st & (age >= 60)
op, hi, lo, cl, pc = [P[k].astype("float64") for k in ("open", "high", "low", "close", "preclose")]
amt = np.where(traded, P["amount"], np.nan).astype("float64")
pct = np.where(traded, P["pctChg"] / 100, np.nan)
adj = np.where(traded, np.cumprod(1 + np.nan_to_num(pct), axis=0), np.nan); adjf = pd.DataFrame(adj).ffill().to_numpy()
kc = np.char.startswith(codes, "sh.68"); cy = np.char.startswith(codes, "sz.30")
lim = np.where(st, 0.05, np.where(kc[None, :] | (cy[None, :] & (dates >= pd.Timestamp("2020-08-24"))[:, None]), 0.20, 0.10))
up = np.floor(pc * (1 + lim) * 100 + 0.5) / 100; dn = np.floor(pc * (1 - lim) * 100 + 0.5) / 100
zt = traded & (np.abs(cl - up) < 0.0051); touch = traded & (hi >= up - 0.0051); onew = traded & (np.abs(op - up) < 0.0051)
dt_ = traded & (np.abs(cl - dn) < 0.0051)
streak = np.zeros((T, N), np.int16); streak[0] = zt[0]
for t in range(1, T):
    streak[t] = (streak[t - 1] + 1) * zt[t]
COST, COST_ETF = 0.003, 0.0005
cyc = pd.read_pickle("/home/claude/bt/_cycle_s.pkl")
phase = cyc["阶段"].reindex(dates).to_numpy(); bullv = cyc["牛"].reindex(dates).fillna(False).astype(bool).to_numpy()
ewr = pd.Series(np.nanmean(np.where(ok, pct, np.nan), 1), index=dates)
per = np.where(dates < pd.Timestamp("2016-01-01"), "", np.where(dates < pd.Timestamp("2021-11-01"), "2016-21", np.where(dates < pd.Timestamp("2024-05-15"), "前半", "后半")))
ORDER = ["冰点", "低位回升", "中高位升温", "高潮", "中高位退潮", "低位回落"]
OUT = {}


def summarize(name, ti, r, ex=None, by_phase=True):
    """ti: 进场日下标（信号日），r: 每笔扣费后收益，ex: 比大盘（同期全A等权）。按天先平均再平均，避免某天几百笔压过别的天。"""
    d = pd.DataFrame({"t": ti, "r": r, "ex": ex if ex is not None else np.nan})
    d = d[np.isfinite(d.r)]
    d["per"] = per[d.t]; d["bull"] = bullv[d.t]; d["ph"] = phase[d.t]
    day = d.groupby("t").agg(r=("r", "mean"), ex=("ex", "mean"), n=("r", "size"))
    day["per"] = per[day.index]; day["bull"] = bullv[day.index]; day["ph"] = phase[day.index]
    row = {"做法": name}
    w5 = day[day.per.isin(["前半", "后半"])]
    row["近5年笔数"] = int(d[d.per.isin(["前半", "后半"])].shape[0]); row["天数"] = len(w5)
    row["每笔"] = w5.r.mean(); row["胜率"] = (d[d.per.isin(["前半", "后半"])].r > 0).mean()
    row["比大盘"] = w5.ex.mean()
    for p_ in ["前半", "后半", "2016-21"]:
        row[p_] = day[day.per == p_].r.mean()
    row["牛"] = w5[w5.bull].r.mean(); row["熊"] = w5[~w5.bull].r.mean()
    row["t"] = w5.r.mean() / w5.r.std() * np.sqrt(len(w5)) if len(w5) > 2 else np.nan
    if by_phase:
        for ph in ORDER:
            row[ph] = w5[w5.ph == ph].r.mean()
    OUT[name] = row
    return d


def fwd_close(ti, j, h):
    """信号日 ti 收盘买、拿 h 天收盘卖（复权）"""
    k = np.minimum(ti + h, T - 1)
    return adjf[k, j] / adjf[ti, j] - 1


def ew_fwd(ti, h):
    e = (1 + ewr.fillna(0)).cumprod().to_numpy()
    k = np.minimum(ti + h, T - 1)
    return e[k] / e[ti] - 1


tt = np.arange(T)
valid = (dates >= pd.Timestamp("2016-01-01"))[:, None] & (tt < T - 3)[:, None]
# ---------------- 打板
prevs = np.vstack([np.zeros((1, N), np.int16), streak[:-1]])
nx_op = np.vstack([op[1:] / pc[1:], np.full((1, N), np.nan)])        # 明天开盘 / 明天前收
nx_cl = np.vstack([cl[1:] / pc[1:], np.full((1, N), np.nan)])
for lab, cond in [("首板打板", prevs == 0), ("连板接力(2进3及以上)", prevs >= 2)]:
    m = ok & touch & ~onew & cond & valid & (age >= 60)
    ti, j = np.nonzero(m)
    base = cl[ti, j] / up[ti, j]                                  # 今天收盘相对买入价
    for fill, fm in [("都能买到", np.ones(len(ti), bool)), ("只买到炸板的", ~zt[ti, j]), ("只买到封住的", zt[ti, j])]:
        for ex_lab, nxt in [("明天开盘卖", nx_op), ("明天收盘卖", nx_cl)]:
            r = base * nxt[ti, j] - 1 - COST
            summarize(f"{lab}·{fill}·{ex_lab}", ti[fm], r[fm])
# ---------------- 涨停次日开盘追（首板封住 → 明天开盘买（不是一字）→ 后天收盘卖）
m = ok & zt & (prevs == 0) & valid
ti, j = np.nonzero(m); ti, j = ti[ti + 2 < T], j[ti + 2 < T]
okb = traded[ti + 1, j] & ~onew[ti + 1, j]
r = (cl[ti + 1, j] / op[ti + 1, j]) * (cl[ti + 2, j] / pc[ti + 2, j]) - 1 - COST
ex = r + COST - (ew_fwd(ti + 1, 1))   # 粗略对照
summarize("涨停次日开盘追·后天收盘卖", ti[okb], r[okb])
# ---------------- 涨停回马枪
first = ok & zt & (prevs == 0) & valid
evs = []
for t0, j0 in zip(*np.nonzero(first)):
    c0, l0 = cl[t0, j0], lo[t0, j0]
    for k in range(t0 + 2, min(t0 + 11, T - 6)):
        if not traded[k, j0]:
            continue
        if lo[k, j0] < l0:
            break
        if cl[k, j0] <= c0 * 0.95:
            evs.append((k, j0)); break
ev = np.array(evs)
if len(ev):
    ti, j = ev[:, 0], ev[:, 1]
    r = fwd_close(ti, j, 5) - COST
    summarize("涨停回马枪·拿5天", ti, r, r + COST - ew_fwd(ti, 5))
# ---------------- 缩量回踩20日线
A = pd.DataFrame(adjf)
ma20 = A.rolling(20).mean().to_numpy(); ma60 = A.rolling(60).mean().to_numpy(); ma60p = np.vstack([np.full((10, N), np.nan), ma60[:-10]])
am20 = pd.DataFrame(amt).rolling(20, min_periods=15).mean().shift(1).to_numpy()
with np.errstate(all="ignore"):
    m = ok & valid & (ma20 > ma60) & (ma60 > ma60p) & (adjf >= ma20 * 0.98) & (adjf <= ma20 * 1.01) & (amt < 0.7 * am20) & (tt < T - 11)[:, None]
ti, j = np.nonzero(m)
r = fwd_close(ti, j, 10) - COST
summarize("缩量回踩20日线·拿10天", ti, r, r + COST - ew_fwd(ti, 10))
del ma20, ma60, ma60p
# ---------------- 超跌反弹
a5 = np.vstack([np.full((5, N), np.nan), adjf[:-5]])
with np.errstate(all="ignore"):
    m = ok & valid & (adjf / a5 - 1 <= -0.15) & ~dt_ & (tt < T - 6)[:, None]
ti, j = np.nonzero(m)
r = fwd_close(ti, j, 5) - COST
summarize("超跌反弹(5天跌15%)·拿5天", ti, r, r + COST - ew_fwd(ti, 5))
# ---------------- 净利润断层
g = pd.read_csv("/home/claude/fund/a_share/growth.csv.xz", usecols=["code", "pubDate", "YOYPNI"], parse_dates=["pubDate"]).dropna()
g = g[g.YOYPNI >= 1.0]
ci = {c: i for i, c in enumerate(codes)}
pe = P["peTTM"].astype("float64")
evs = []
for c, d0 in zip(g.code, g.pubDate):
    j0 = ci.get(c)
    if j0 is None:
        continue
    k = dates.searchsorted(d0, side="right")          # 公告后第一个交易日
    if k >= T - 61 or not ok[k, j0]:
        continue
    gp = op[k, j0] / pc[k, j0] - 1
    if gp >= 0.02 and cl[k, j0] >= op[k, j0] and not onew[k, j0] and pe[k, j0] > 0:
        evs.append((k, j0))
ev = np.array(evs)
if len(ev):
    ti, j = ev[:, 0], ev[:, 1]
    for h in (20, 60):
        r = fwd_close(ti, j, h) - COST
        summarize(f"净利润断层·拿{h}天", ti, r, r + COST - ew_fwd(ti, h), by_phase=False)
# ---------------- 隔夜持股（全部股票 / 小盘）
with np.errstate(all="ignore"):
    on = nx_op - 1
m = ok & valid
ti, j = np.nonzero(m)
day_on = pd.Series(on[ti, j]).groupby(ti).mean()
OUT["隔夜持股·全部股票平均(不扣费)"] = {"做法": "隔夜持股·全部股票平均(不扣费)", "每笔": day_on[per[day_on.index] != "2016-21"].mean(),
                               "前半": day_on[per[day_on.index] == "前半"].mean(), "后半": day_on[per[day_on.index] == "后半"].mean(), "2016-21": day_on[per[day_on.index] == "2016-21"].mean()}
del on

# ---------------- 指数类：二八轮动、均线择时、节前效应
ix = load.a_share_index(start="2015-01-01")
IX = {c: g_.set_index("date").sort_index() for c, g_ in ix.groupby("code")}
c300, c1000 = IX["sh.000300"].close, IX["sh.000852"].close
cc = pd.DataFrame({"300": c300, "1000": c1000}).dropna()
rr = cc.pct_change()


def idx_stats(name, dret):
    dret = dret.dropna()
    def ann(x):
        if not len(x): return np.nan
        return (1 + x).prod() ** (250 / len(x)) - 1
    def mdd(x):
        e = (1 + x).cumprod(); return (e / e.cummax() - 1).min()
    w5 = dret["2021-11-01":]
    OUT[name] = {"做法": name, "年化": ann(w5), "最大回撤": mdd(w5), "前半": ann(dret["2021-11-01":"2024-05-14"]), "后半": ann(dret["2024-05-15":]), "2016-21": ann(dret["2016-01-01":"2021-10-31"])}


fri = cc.index[cc.index.to_series().dt.dayofweek == 4]
mom = cc / cc.shift(20) - 1
hold = pd.Series(index=cc.index, dtype=object)
cur = None
for d in cc.index:
    hold[d] = cur
    if d in fri:
        m_ = mom.loc[d]
        cur = None if m_.isna().any() or (m_ < 0).all() else m_.idxmax()
sw = (hold != hold.shift()).astype(float)
r28 = pd.Series([rr.loc[d, h] if h in ("300", "1000") else 0.0 for d, h in hold.items()], index=cc.index) - sw * COST_ETF
idx_stats("二八轮动(沪深300/中证1000，每周)", r28["2016-01-01":])
idx_stats("一直拿沪深300", rr["300"]["2016-01-01":]); idx_stats("一直拿中证1000", rr["1000"]["2016-01-01":])
ma = c1000.rolling(20).mean(); sig = (c1000 > ma).shift(1).reindex(cc.index).fillna(False)
rma = rr["1000"].where(sig, 0.0) - (sig != sig.shift()).astype(float) * COST_ETF
idx_stats("均线择时(中证1000在20日线上才拿)", rma["2016-01-01":])
ewi = (1 + ewr.fillna(0)).cumprod(); ewma = ewi.rolling(20).mean(); s2 = (ewi > ewma).shift(1).fillna(False)
idx_stats("均线择时(全A等权在20日线上才拿)", (ewr.fillna(0).where(s2, 0.0) - (s2 != s2.shift()).astype(float) * COST_ETF)["2016-01-01":])
idx_stats("一直拿全A等权", ewr.fillna(0)["2016-01-01":])
# 节前效应
gaps = pd.Series(dates[1:] - dates[:-1], index=dates[:-1])
hol = [i for i, d in enumerate(dates[:-1]) if gaps.iloc[i] >= pd.Timedelta(days=5) and d >= pd.Timestamp("2016-01-01")]
rows = []
e = (1 + ewr.fillna(0)).cumprod().to_numpy()
for i in hol:
    if i - 5 < 0 or i + 2 >= T:
        continue
    pre = e[i] / e[i - 5] - 1; post = e[i + 2] / e[i] - 1
    rows.append((dates[i], dates[i].month, pre, post))
H = pd.DataFrame(rows, columns=["d", "m", "pre", "post"])
H["kind"] = np.where(H.m.isin([1, 2]), "春节", np.where(H.m.isin([9, 10]), "国庆", "其他"))
print("\n== 节前效应（全A等权）：节前5天 / 节后2天 ==")
for k_, x in H.groupby("kind"):
    print(f"{k_}: {len(x)}次 节前5天平均 {x.pre.mean()*100:+.2f}%（涨{(x.pre>0).mean():.0%}） 节后2天 {x.post.mean()*100:+.2f}%（涨{(x.post>0).mean():.0%}）",
          "近5年:", [f"{d.date()} {p*100:+.1f}/{q*100:+.1f}" for d, p, q in zip(x.d, x.pre, x.post) if d >= pd.Timestamp("2021-11-01")])
# 行业轮动
ind = pd.read_csv("/home/claude/market-data/a_share/meta/industry.csv", dtype=str).set_index("code").industry.reindex(codes).fillna("").str[:3].to_numpy()
inds = sorted(set(ind) - {""})
IR = pd.DataFrame({k: np.nanmean(np.where(ok[:, ind == k], pct[:, ind == k], np.nan), 1) for k in inds if (ind == k).sum() >= 20}, index=dates)
II = (1 + IR.fillna(0)).cumprod(); M20 = II / II.shift(20) - 1
hold = None; rows_r = []; prev = set()
fri2 = set(dates[dates.dayofweek == 4])
for k_, d in enumerate(dates):
    if hold:
        rows_r.append((d, IR.loc[d, list(hold)].mean()))
    else:
        rows_r.append((d, np.nan))
    if d in fri2 and d >= pd.Timestamp("2015-06-01"):
        top = M20.loc[d].dropna().sort_values(ascending=False).index[:3]
        newh = set(top); turn = 1 - len(newh & prev) / 3 if prev else 1
        hold = newh; prev = newh
rot = pd.Series(dict(rows_r)).astype(float)
idx_stats("行业轮动(最强3个行业，每周换)", (rot - ewr).dropna()["2016-01-01":] + 0)   # 这里存的是超额
OUT["行业轮动(最强3个行业，每周换)"]["做法"] = "行业轮动·比全A等权的超额(年化)"

pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40)
O = pd.DataFrame(OUT.values())
pc_ = lambda v: "" if v is None or (isinstance(v, float) and not np.isfinite(v)) else (f"{v*100:+.2f}%" if isinstance(v, float) else v)
cols1 = ["做法", "近5年笔数", "天数", "每笔", "胜率", "比大盘", "前半", "后半", "2016-21", "牛", "熊", "t"] + ORDER
S = O[O["近5年笔数"].notna()][cols1].copy()
for c in cols1[3:]:
    S[c] = S[c].map(lambda v: "" if not isinstance(v, float) or not np.isfinite(v) else (f"{v:.1f}" if c == "t" else (f"{v*100:.0f}%" if c == "胜率" else f"{v*100:+.2f}%")))
print("\n== 短线/波段做法（每笔扣 0.3% 后的平均，先按天平均）==")
print(S.to_string(index=False))
I_ = O[O["年化"].notna()][["做法", "年化", "最大回撤", "前半", "后半", "2016-21"]].copy() if "年化" in O else None
if I_ is not None:
    for c in I_.columns[1:]:
        I_[c] = I_[c].map(lambda v: f"{v*100:+.1f}%" if isinstance(v, float) and np.isfinite(v) else "")
    print("\n== 指数/轮动类（年化）==")
    print(I_.to_string(index=False))
print("\n隔夜持股（不扣费，每天全部股票平均）：", {k: f"{v*100:+.3f}%" for k, v in OUT["隔夜持股·全部股票平均(不扣费)"].items() if k != "做法"})
pd.to_pickle(OUT, "/home/claude/bt/_trader_out.pkl")
