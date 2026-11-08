"""A股趋势启动 × 环境（2016–2026）。
启动的定义按个股自身波动率：次日收盘买入后20个交易日涨幅 ≥ 2倍该股20日波动（过去60天日波动×√20）。
三种启动前形态（事先定好，不按结果挑）：
  S1 收敛后突破：前一天20日振幅不到自身一年中位数的60%，今天收盘突破前20日最高
  S2 均线金叉：20日线上穿60日线
  S3 上升趋势回踩：上升趋势中，前10天曾高出20日线6%以上，今天回到20日线附近（-3%~+1%）
基准：同一环境下所有股票、所有日子的启动概率。
环境：全A等权指数在200日线上/下（牛/熊）× 情绪温度（偏冷<40 / 中性 / 偏热>60）。
每天先把当天的信号平均，再对日期平均。"""
import sys
sys.path.insert(0, "/home/claude/bt"); sys.path.insert(0, "/home/claude/src/Jsq")
import os
os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np
import pandas as pd
from sentiment import compute
from market_data import load

s, g, m = compute()
temp = pd.read_csv("/home/claude/bt/sentiment_temp.csv", index_col=0, parse_dates=True)
dates, codes = g["dates"], g["codes"]
ok, adj, age, traded = m["ok"], m["adj"], m["age"], m["traded"]
base = ok & (age >= 250)
A = pd.DataFrame(adj)
adjf = A.ffill().to_numpy()
r = pd.DataFrame(np.where(traded, g["pctChg"] / 100.0, np.nan))
sig20 = (r.rolling(60, min_periods=40).std() * np.sqrt(20)).to_numpy()
ma20 = m["ma20"]; ma60 = m["ma60"]
ma60_lag = pd.DataFrame(ma60).shift(10).to_numpy()
up = (adj > ma60) & (ma20 > ma60) & (ma60 > ma60_lag)
down = (adj < ma60) & (ma20 < ma60) & (ma60 < ma60_lag)
state = np.where(up, "上升", np.where(down, "下跌", "震荡"))

# 结果：次日收盘买入，之后20天
H = 20
T = len(dates)
entry = np.vstack([adjf[1:], np.full((1, adjf.shape[1]), np.nan)])
exitp = np.vstack([adjf[1 + H:], np.full((1 + H, adjf.shape[1]), np.nan)])
fwd = exitp / entry - 1
start = fwd >= 2 * sig20
ew = s["等权指数"].to_numpy()
ew_fwd = np.full(T, np.nan); ew_fwd[:T - 1 - H] = ew[1 + H:] / ew[1:T - H] - 1

# 形态
hi20_prev = A.shift(1).rolling(20, min_periods=18).max().to_numpy()
lo20 = A.rolling(20, min_periods=18).min().to_numpy(); hi20 = A.rolling(20, min_periods=18).max().to_numpy()
rng = pd.DataFrame((hi20 - lo20) / adj)
rng_med = rng.rolling(250, min_periods=200).median()
squeeze_prev = (rng < 0.6 * rng_med).shift(1).fillna(False).to_numpy().astype(bool)
S1 = base & squeeze_prev & (adj > hi20_prev)
gc = (ma20 > ma60)
S2 = base & gc & ~np.vstack([np.ones((1, gc.shape[1]), bool), gc[:-1]])
ext10 = A.shift(1).rolling(10, min_periods=8).max().to_numpy() >= 1.06 * ma20
S3 = base & up & (adj <= 1.01 * ma20) & (adj >= 0.97 * ma20) & ext10
SETUPS = {"基准(全部)": base, "S1 收敛后突破": S1, "S2 均线金叉": S2, "S3 上升趋势回踩": S3}

st = load.a_share_stocks().set_index("code")
ind = st["industry"].reindex(codes).fillna("").to_numpy()
tech = np.isin(np.array([x[:3] for x in ind]), ["C39", "I65", "I64", "I63"])
UNIV = {"科技股": tech, "全A": np.ones(len(codes), bool)}

env = temp.reindex(dates)
band = pd.cut(env["温度"], [-1, 40, 60, 101], labels=["偏冷", "中性", "偏热"]).astype(str).to_numpy()
reg = env["牛熊"].astype(str).str[:1].to_numpy()
half = np.where(dates < pd.Timestamp("2021-01-01"), "2016-20", "2021-26")
valid_t = (dates >= pd.Timestamp("2016-01-01")) & np.isfinite(ew_fwd)

rows = []
for un, umask in UNIV.items():
    for sn, S in SETUPS.items():
        M = S & umask[None, :] & np.isfinite(fwd) & np.isfinite(sig20)
        cnt = M.sum(1)
        p_start = np.where(cnt > 0, (M & start).sum(1) / np.maximum(cnt, 1), np.nan)
        f_mean = np.where(cnt > 0, np.nansum(np.where(M, fwd, 0), 1) / np.maximum(cnt, 1), np.nan)
        d = pd.DataFrame({"date": dates, "cnt": cnt, "p": p_start, "f": f_mean, "ex": f_mean - ew_fwd,
                          "reg": reg, "band": band, "half": half, "valid": valid_t})
        d = d[d.valid & (d.cnt > 0)]
        d["univ"], d["setup"] = un, sn
        rows.append(d)
D = pd.concat(rows)
D.to_csv("/home/claude/bt/trendstart_daily.csv", index=False)


def agg(x):
    return pd.Series({"信号日": len(x), "信号数": int(x.cnt.sum()), "启动概率": x.p.mean(), "20天平均": x.f.mean(), "跑赢全A": x.ex.mean()})


pd.set_option("display.width", 250)
for un in UNIV:
    sub = D[D.univ == un]
    print(f"\n################ {un}")
    t = sub.groupby(["setup"]).apply(agg, include_groups=False)
    print(t.assign(启动概率=t.启动概率.map("{:.1%}".format), **{"20天平均": t["20天平均"].map("{:+.1%}".format), "跑赢全A": t["跑赢全A"].map("{:+.1%}".format)}).to_string())
    t2 = sub.groupby(["reg", "band", "setup"]).apply(agg, include_groups=False)
    piv_p = t2["启动概率"].unstack("setup")
    lift = piv_p.div(piv_p["基准(全部)"], axis=0)
    piv_ex = t2["跑赢全A"].unstack("setup")
    print("\n启动概率（基准=同环境下所有股票）:"); print(piv_p.map("{:.1%}".format).to_string())
    print("\n相对基准的倍数:"); print(lift.map("{:.2f}".format).to_string())
    print("\n之后20天跑赢全A:"); print(piv_ex.map("{:+.1%}".format).to_string())
    t3 = sub.groupby(["half", "reg", "band", "setup"]).apply(agg, include_groups=False)
    ex3 = t3["跑赢全A"].unstack("setup").drop(columns="基准(全部)")
    print("\n前后两半：跑赢全A"); print(ex3.map("{:+.1%}".format).to_string())
