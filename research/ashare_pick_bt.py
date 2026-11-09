"""A股正股选股回测：成长 × 主线 × 情绪（只用当时已公告的财报）。
每月最后一个交易日 t 收盘选股，看之后20个交易日（和60个交易日）相对"全体可选股票等权平均"的超额收益。
可选股票：t 日正常交易、非ST、上市满250个交易日、近20日日均成交额 ≥ 3000万。收益用 pctChg 连乘（复权口径）。
因子（都只用 t 及以前的信息）：
  growth   最新已公告季度的归母净利润同比（YOYPNI，累计口径）
  accel    最新一期增速 − 上一期增速（增速在加快）
  roe      最新已公告 ROE
  ind_heat 所在行业近20日成交额占全市场比例 ÷ 过去250日平均占比（主线：钱在往里流）
  mom120   近120日涨幅（跳过最近5日）——市场已经在买的
  temp/bull 全市场情绪温度、等权全A在200日线上/下（择时条件，不是选股因子）
2024-05 → 2026-09 共29个月；前后两段 2025-07 分界。"""
import numpy as np, pandas as pd

P = "/home/claude/bt/panel"
dates = pd.to_datetime(np.load(f"{P}/dates.npy"))
codes = np.load(f"{P}/codes.npy")
L = lambda k: np.load(f"{P}/{k}.npy")
pct, amt, st, ts = L("pctChg"), L("amount"), L("isST"), L("tradestatus")
pct = np.where(np.isfinite(pct), pct, 0.0) / 100
logr = np.log1p(pct)
cum = np.vstack([np.zeros(len(codes)), np.cumsum(logr, 0)])     # cum[i] = 到第 i-1 天收盘的累计对数收益
fwd = lambda t, h: np.expm1(cum[t + 1 + h] - cum[t + 1])          # t 收盘 → t+h 收盘
back = lambda t, a, b: np.expm1(cum[t + 1 - b] - cum[t + 1 - a])  # t-a 收盘 → t-b 收盘

# 行业
ind = pd.read_csv("/home/claude/market-data/a_share/meta/industry.csv").set_index("code").industry
ind_of = np.array([ind.get(c) if isinstance(ind.get(c), str) else "" for c in codes])
inds = sorted(set(ind_of) - {""})
iidx = {k: i for i, k in enumerate(inds)}
ind_id = np.array([iidx.get(x, -1) for x in ind_of])
amt0 = np.where(np.isfinite(amt), amt, 0.0)
tot = amt0.sum(1)
ish = np.zeros((len(dates), len(inds)))
for j in range(len(inds)):
    ish[:, j] = amt0[:, ind_id == j].sum(1) / np.maximum(tot, 1)

# 财报（按公告日）
g = pd.read_csv("/home/claude/fund/a_share/growth.csv.xz", parse_dates=["pubDate", "statDate"])
pr = pd.read_csv("/home/claude/fund/a_share/profit.csv.xz", parse_dates=["pubDate", "statDate"])
f = g.merge(pr[["code", "statDate", "roeAvg"]], on=["code", "statDate"], how="left").sort_values(["code", "statDate"])
f["prev"] = f.groupby("code").YOYPNI.shift(1)
f = f.dropna(subset=["pubDate"])

tmp = pd.read_csv("/home/claude/bt/sentiment_temp.csv", index_col=0, parse_dates=True)
cpos = {c: i for i, c in enumerate(codes)}


def month_ends(start, end):
    s = pd.Series(np.arange(len(dates)), index=dates)
    s = s[(s.index >= start) & (s.index <= end)]
    return s.groupby([s.index.year, s.index.month]).max().to_numpy()


def snapshot(t):
    day = dates[t]
    avail = f[f.pubDate < day]                         # 公告日在 t 之前
    last = avail.groupby("code").tail(1).set_index("code")
    X = pd.DataFrame(index=codes)
    X["growth"] = last.YOYPNI.reindex(codes).to_numpy()
    X["accel"] = (last.YOYPNI - last.prev).reindex(codes).to_numpy()
    X["roe"] = last.roeAvg.reindex(codes).to_numpy()
    X["age"] = (day - last.statDate).dt.days.reindex(codes).to_numpy()
    heat = ish[t - 19:t + 1].mean(0) / np.maximum(ish[t - 249:t + 1].mean(0), 1e-9)
    X["ind_heat"] = np.where(ind_id >= 0, heat[np.maximum(ind_id, 0)], np.nan)
    X["mom120"] = back(t, 120, 5)
    X["mom20"] = back(t, 20, 0)
    a20 = amt0[t - 19:t + 1].mean(0)
    listed = np.isfinite(L_close[t - 249]) if False else (np.count_nonzero(amt0[t - 249:t + 1] > 0, axis=0) >= 200)
    ok = (ts[t] == 1) & (st[t] == 0) & listed & (a20 >= 3e7) & (X.age.to_numpy() < 200)
    X["ok"] = ok
    X["f20"] = fwd(t, 20) if t + 21 <= len(dates) else np.nan
    X["f60"] = fwd(t, 60) if t + 61 <= len(dates) else np.nan
    X["date"] = day
    X["temp"] = tmp["温度"].reindex([day]).iloc[0] if day in tmp.index else np.nan
    X["bull"] = tmp["牛熊"].reindex([day]).iloc[0] if day in tmp.index else np.nan
    X["ind"] = ind_of
    return X[X.ok]


L_close = None
if __name__ == "__main__":
    snaps = [snapshot(t) for t in month_ends("2023-05-01", "2026-10-31")]
    S = pd.concat(snaps).reset_index(names="code")
    S.to_csv("ashare_pick_snap23.csv.xz", index=False)
    print(S.groupby("date").agg(n=("code", "size"), growth_ok=("growth", lambda x: x.notna().mean()), temp=("temp", "first"), bull=("bull", "first")).to_string())
