"""A股选股方法系统筛选（月度换仓）。
每月第一个交易日开盘买、持有20个交易日（到第20天收盘）；所有指标只用前一个交易日收盘之前的数据。
范围：正常交易、非ST、上市满250个交易日、近20日日均成交额 ≥ 3000万（不含北交所）；当天开盘涨停买不进的剔除。
看每个指标排前20%（按"好"的方向）的股票，比范围内等权平均多涨多少；近5年（2021-11→2026-10）为主，前后两段 + 2016-2021 对照，牛熊分开。
用法: python3 ashare_factor_bt.py
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apanel

P = apanel.build(extra=True)
dates = pd.to_datetime(P["dates"]); codes = P["codes"].astype(str); T, N = P["close"].shape
f32 = lambda a: a.astype("float32")
traded = (np.nan_to_num(P["tradestatus"]) == 1) & np.isfinite(P["close"]) & (np.nan_to_num(P["amount"]) > 0)
st = np.nan_to_num(P["isST"]).astype(bool)
age = np.cumsum(traded, axis=0)
pct = np.where(traded, P["pctChg"], np.nan).astype("float32") / 100
ret0 = np.nan_to_num(pct)
adj = np.where(traded, np.cumprod(1 + ret0.astype("float64"), axis=0), np.nan).astype("float32")
adjf = pd.DataFrame(adj).ffill().to_numpy(dtype="float32")
op, cl, pc = P["open"], P["close"], P["preclose"]
amt = np.where(traded, P["amount"], np.nan).astype("float32")

# 月初换仓日
s_d = pd.Series(np.arange(T), index=dates)
reb = [int(g.iloc[0]) for _, g in s_d.groupby([dates.year, dates.month])]
reb = [i for i in reb if i >= 260 and i + 20 < T and dates[i] >= pd.Timestamp("2016-01-01")]
R = np.array(reb); print("换仓次数", len(R), dates[R[0]].date(), "→", dates[R[-1]].date())

F = {}            # 指标名 → (len(R) × N)，取 t-1 那一行
def take(M):
    return np.asarray(M)[R - 1].astype("float32")

def roll(M, w, fn, minp=None):
    D = pd.DataFrame(M)
    r = getattr(D.rolling(w, min_periods=minp or int(w * 0.75)), fn)()
    return take(r.to_numpy(dtype="float32"))

with np.errstate(all="ignore"):
    F["近20日涨幅"] = take(adjf) / take(np.vstack([np.full((20, N), np.nan, "float32"), adjf[:-20]])) - 1
    F["近5日涨幅"] = take(adjf) / take(np.vstack([np.full((5, N), np.nan, "float32"), adjf[:-5]])) - 1
    a20 = np.vstack([np.full((20, N), np.nan, "float32"), adjf[:-20]]); a250 = np.vstack([np.full((250, N), np.nan, "float32"), adjf[:-250]])
    F["一年动量(去掉近一月)"] = take(a20) / take(a250) - 1
    del a20, a250
    F["20日波动"] = roll(pct, 20, "std")
    F["60日波动"] = roll(pct, 60, "std")
    turn = np.where(traded, P["turn"], np.nan).astype("float32")
    F["20日换手"] = roll(turn, 20, "mean")
    t250 = roll(turn, 250, "mean", 150); F["换手放大(20日/一年)"] = F["20日换手"] / t250
    del turn
    F["20日最大单日涨幅"] = roll(pct, 20, "max")
    F["20日成交额"] = roll(amt, 20, "mean")
    fcap = np.where(traded & (P["turn"] > 0), P["amount"] / (P["turn"] / 100), np.nan).astype("float32") / 1e8   # 成交额/换手率 ≈ 流通市值（亿）
    F["流通市值"] = roll(fcap, 20, "median", 10)
    del fcap
    F["流动性差(Amihud)"] = roll(np.abs(pct) / amt * 1e8, 20, "mean")
    mx = roll(adjf, 250, "max", 200); F["离一年高点"] = take(adjf) / mx - 1
    ma60 = roll(adjf, 60, "mean"); F["站上60日线"] = take(adjf) / ma60 - 1
    ma200 = roll(adjf, 200, "mean"); F["站上200日线"] = take(adjf) / ma200 - 1
    pe = take(np.where(traded, P["peTTM"], np.nan)); pb = take(np.where(traded, P["pbMRQ"], np.nan))
    F["盈利收益率(1/PE)"] = 1 / pe; F["净资产收益比(1/PB)"] = 1 / pb
    # 涨停次数
    kc = np.char.startswith(codes, "sh.68"); cy = np.char.startswith(codes, "sz.30")
    lim = np.where(st, 0.05, np.where(kc[None, :] | (cy[None, :] & (dates >= pd.Timestamp("2020-08-24"))[:, None]), 0.20, 0.10))
    up = np.floor(pc.astype("float64") * (1 + lim) * 100 + 0.5) / 100
    zt = (traded & (np.abs(cl - up) < 0.0051)).astype("float32")
    F["20日涨停次数"] = roll(zt, 20, "sum", 10)
    # 现金分红（除息日：前收 < 昨收、比例 0~10% 视为现金分红；送转股比例大，排除）
    prev_cl = np.vstack([np.full((1, N), np.nan), cl[:-1]])
    dr = np.where(traded, 1 - pc / prev_cl, 0); dr = np.where((dr > 0.0005) & (dr < 0.10), dr, 0).astype("float32")
    F["近一年股息率"] = roll(dr, 250, "sum", 200)
    del dr, prev_cl, up, zt, lim
    # 市值（总股本取最近一期已公告财报）
    prof = pd.read_csv("/home/claude/fund/a_share/profit.csv.xz", usecols=["code", "pubDate", "statDate", "roeAvg", "totalShare", "npMargin"],
                       parse_dates=["pubDate", "statDate"])
    grow = pd.read_csv("/home/claude/fund/a_share/growth.csv.xz", usecols=["code", "pubDate", "statDate", "YOYPNI", "YOYEquity"],
                       parse_dates=["pubDate", "statDate"])
    ci = {c: j for j, c in enumerate(codes)}

    def latest(df, col, prev=False):
        out = np.full((len(R), N), np.nan, "float32")
        df = df.dropna(subset=["pubDate"]).sort_values(["code", "statDate"])
        if prev:
            df = df.assign(**{col: df[col] - df.groupby("code")[col].shift(1)})
        for k, i in enumerate(R):
            d0 = dates[i]
            x = df[(df.pubDate < d0) & (df.statDate > d0 - pd.Timedelta(days=270))].groupby("code").last()
            j = np.array([ci.get(c, -1) for c in x.index], dtype=int); m = j >= 0
            if m.any():
                out[k, j[m]] = x[col].to_numpy()[m]
        return out
    sh = latest(prof, "totalShare")
    F["总市值"] = take(cl) * sh / 1e8
    F["ROE"] = latest(prof, "roeAvg")
    F["净利润增速"] = latest(grow, "YOYPNI")
    F["净利润增速变化"] = latest(grow, "YOYPNI", prev=True)
    F["净资产增速"] = latest(grow, "YOYEquity")

# 可买范围 & 收益
U = (traded & ~st & (age >= 250))[R - 1] & (F["20日成交额"] >= 3e7)
ok_t = traded[R] & ~(np.abs(op[R] - np.floor(pc[R].astype("float64") * 1.1 * 100 + 0.5) / 100) < 0.0051)   # 主板开盘涨停粗略剔除
U &= ok_t
with np.errstate(all="ignore"):
    fwd = adjf[R + 19] / adjf[R] * (cl[R] / op[R]) - 1          # 当天开盘买 → 第20个交易日收盘
U &= np.isfinite(fwd)
# 牛熊：全A等权指数 vs 200日线（同工作台），看换仓前一天
ew = np.nanmean(np.where(traded & ~st & (age >= 20), pct, np.nan), 1)
ewi = pd.Series(np.cumprod(1 + np.nan_to_num(ew)), index=dates)
bull = (ewi > ewi.rolling(200).mean()).to_numpy()[R - 1]
rd = dates[R]
per = np.where(rd < pd.Timestamp("2021-11-01"), "2016-21", np.where(rd < pd.Timestamp("2024-05-01"), "前半", "后半"))
np.savez("/home/claude/bt/_factor_base.npz", R=R, fwd=fwd, U=U, bull=bull, per=per, rd=rd.values.astype("datetime64[D]"))
pd.to_pickle(F, "/home/claude/bt/_factors.pkl")

rows = []
for name, X in F.items():
    q5 = []; q1 = []
    for k in range(len(R)):
        m = U[k] & np.isfinite(X[k])
        if m.sum() < 300:
            q5.append(np.nan); q1.append(np.nan); continue
        x, y = X[k, m], fwd[k, m]; base = np.nanmean(fwd[k, U[k]])
        lo, hi = np.nanquantile(x, [0.2, 0.8])
        q5.append(np.nanmean(y[x >= hi]) - base); q1.append(np.nanmean(y[x <= lo]) - base)
    q5, q1 = np.array(q5), np.array(q1)
    sgn = 1 if np.nanmean(q5[per != "2016-21"]) >= np.nanmean(q1[per != "2016-21"]) else -1
    best = q5 if sgn == 1 else q1
    r = {"指标": name, "好的方向": "高" if sgn == 1 else "低"}
    for lab, m in [("近5年", per != "2016-21"), ("前半", per == "前半"), ("后半", per == "后半"), ("2016-21", per == "2016-21"),
                   ("5年牛", (per != "2016-21") & bull), ("5年熊", (per != "2016-21") & ~bull)]:
        v = best[m]; v = v[np.isfinite(v)]
        r[lab] = v.mean() * 100 if len(v) else np.nan
        if lab == "近5年":
            r["跑赢月份"] = f"{(v > 0).sum()}/{len(v)}"; r["t"] = v.mean() / v.std() * np.sqrt(len(v))
    rows.append(r)
O = pd.DataFrame(rows)
O["稳"] = (O["前半"] > 0) & (O["后半"] > 0) & ((O["2016-21"] > 0) | O["2016-21"].isna())
O = O.sort_values("近5年", ascending=False)
pd.set_option("display.width", 250)
print("\n== 每个指标排前20%（按好的方向）的股票，之后一个月比全部平均多涨（%/月）==")
print(O.round(2).to_string(index=False))
O.to_pickle("/home/claude/bt/_factor_table.pkl")
