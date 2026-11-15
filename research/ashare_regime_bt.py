"""全A大盘阶段：当天能看到的市场指标，能不能分出之后 20/60/120 个交易日全A（等权）的好坏。2026-11-15 定稿后才跑，分档跑前写死。
指标（都只用当天及之前的数据；股票范围 = 当天成交、非ST、上市满250天、20日均成交≥3000万）：
  b200  站在自己200日线上方的股票占比            分档 <20% / 20~40 / 40~60 / 60~80 / >80%
  nl    创250日新低的股票占比（5日平均）          分档 <3% / 3~10% / >10%
  dd    全A等权离250日最高点的回撤                分档 >−10% / −10~−20 / −20~−30 / <−30%
  t20   情绪温度20日平均                          分档 <35 / 35~50 / 50~65 / >65
  vr    全市场成交额 20日平均 ÷ 250日平均          分档 <0.7 / 0.7~1 / 1~1.5 / >1.5
  tr    全A等权在200日线 上 / 下
取样：每20个交易日取一天（20天的结果互不重叠；60/120天的有重叠，只看方向和分段是否一致，不做显著性）。
分四段：2016-07→2018-12、2019-01→2021-10、2021-11→2023-12、2024-01→2026-05。数据以前都看过，不称样本外。
另：事后用"全A等权转折≥25%"标出大底和大顶（只用来描述，不是当时能知道的），看各指标在这些日子的读数。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ashare_swing_bt import world, pct

BLK = [("2016-07-01", "2018-12-31"), ("2019-01-01", "2021-10-31"), ("2021-11-01", "2023-12-31"), ("2024-01-01", "2026-05-31")]
BINS = {"b200": ([0, .2, .4, .6, .8, 1.01], ["<20%", "20~40%", "40~60%", "60~80%", ">80%"]),
        "nl": ([0, .03, .10, 1.01], ["<3%", "3~10%", ">10%"]),
        "dd": ([-1, -.30, -.20, -.10, 0.001], ["<−30%", "−30~−20%", "−20~−10%", ">−10%"]),
        "t20": ([0, 35, 50, 65, 101], ["<35", "35~50", "50~65", ">65"]),
        "vr": ([0, .7, 1, 1.5, 99], ["<0.7", "0.7~1", "1~1.5", ">1.5"])}


def features(W):
    adj, U, d = W["adj"], W["U"], W["dates"]; A = pd.DataFrame(adj)
    ma200 = A.rolling(200, min_periods=150).mean().to_numpy(); lo250 = A.rolling(250, min_periods=200).min().to_numpy()
    n = U.sum(1).astype(float); n[n == 0] = np.nan
    ew = pd.Series(W["ref"]["全A等权"], index=d); amt = pd.Series(np.nansum(W["amt"], axis=1), index=d)
    F = pd.DataFrame(index=d)
    F["b200"] = (U & (adj > ma200)).sum(1) / n
    F["nl"] = pd.Series((U & (adj <= lo250 * 1.0001)).sum(1) / n, index=d).rolling(5).mean()
    F["dd"] = ew / ew.rolling(250, min_periods=200).max() - 1
    F["t20"] = W["s"]["温度"].rolling(20).mean().to_numpy()
    F["vr"] = amt.rolling(20).mean() / amt.rolling(250, min_periods=200).mean()
    F["tr"] = np.where(ew > ew.rolling(200).mean(), "线上", "线下")
    for H in (20, 60, 120):
        F[f"f{H}"] = ew.shift(-H) / ew - 1
    F["fdd60"] = [ew.iloc[i:i + 61].min() / ew.iloc[i] - 1 if i + 60 < len(ew) else np.nan for i in range(len(ew))]
    F["ew"] = ew
    return F


def table(S, col, labels=None):
    out = []
    for k, x in S.groupby(col, observed=True):
        row = {col: k, "次数": len(x), "20天": pct(x.f20.mean()), "60天": pct(x.f60.mean()), "120天": pct(x.f120.mean()),
               "60天上涨比例": f"{(x.f60 > 0).mean():.0%}", "60天内最深再跌(平均)": pct(x.fdd60.mean())}
        for i in range(4):
            y = x[x.blk == i]; row[f"段{i+1} 60天(n)"] = f"{pct(y.f60.mean())}({len(y)})" if len(y) else "—"
        out.append(row)
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    W = world("2015-01-01"); F = features(W); d = W["dates"]
    F.to_pickle("/tmp/_regime_F.pkl")
    S = F.iloc[::20].copy(); S = S[(S.index >= "2016-07-01")]
    S["blk"] = -1
    for i, (a, b) in enumerate(BLK): S.loc[(S.index >= a) & (S.index <= b), "blk"] = i
    S = S[S.f20.notna()]
    print(f"取样 {len(S)} 天（{S.index[0].date()} → {S.index[-1].date()}）；全部平均：20天 {pct(S.f20.mean())}，60天 {pct(S.f60.mean())}，120天 {pct(S.f120.mean())}")
    for k, (edges, labs) in BINS.items():
        S[k + "_b"] = pd.cut(S[k], edges, labels=labs, right=False)
        print(f"\n== {k}"); table(S, k + "_b")
    print("\n== tr 全A在200日线"); table(S, "tr")
    # 事后标出大底大顶
    ew = F.ew[F.index >= "2016-01-01"]; piv = []; mode = None; hi = lo = ew.index[0]
    for t, x in ew.items():
        if mode in (None, "up"):
            if x > ew[hi]: hi = t
            if x <= ew[hi] * 0.75 and mode != "dn":
                piv.append(("顶", hi)); mode = "dn"; lo = ew[hi:t].idxmin()
        if mode in (None, "dn"):
            if x < ew[lo]: lo = t
            if x >= ew[lo] * 1.25:
                piv.append(("底", lo)); mode = "up"; hi = ew[lo:t].idxmax()
    print("\n事后标出的大底/大顶（全A等权转折≥25%）和当天读数：")
    rows = []
    for k, t in piv:
        r = F.loc[t]; i = F.index.get_loc(t)
        rows.append({"": k, "日期": t.date(), "b200": f"{r.b200:.0%}", "nl": f"{r.nl:.0%}", "dd": pct(r.dd), "t20": f"{r.t20:.0f}", "vr": f"{r.vr:.2f}", "200日线": r.tr,
                     "之后60天": pct(r.f60), "之后120天": pct(r.f120)})
    print(pd.DataFrame(rows).to_string(index=False))
    r = F.iloc[-1]; print(f"\n现在（{F.index[-1].date()}）：b200 {r.b200:.0%}，nl {r.nl:.1%}，dd {pct(r.dd)}，t20 {r.t20:.0f}，vr {r.vr:.2f}，200日线{r.tr}")
    pd.to_pickle(piv, "/tmp/_regime_piv.pkl")
