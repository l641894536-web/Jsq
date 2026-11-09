import pandas as pd, numpy as np, sys
S = pd.read_csv("ashare_pick_snap23.csv.xz", parse_dates=["date"])
S["bull"] = S.bull.astype(str).str.startswith("牛")
MID = pd.Timestamp("2025-01-01")
H = sys.argv[1] if len(sys.argv) > 1 else "f20"
S = S[S[H].notna()].copy()
S["ex"] = S[H] - S.groupby("date")[H].transform("mean")
for c in ["growth", "accel"]:
    lo, hi = S[c].quantile([.01, .99]); S[c] = S[c].clip(lo, hi)


def qtab(col, q=5):
    x = S.dropna(subset=[col]).copy()
    x["q"] = x.groupby("date")[col].transform(lambda v: pd.qcut(v.rank(method="first"), q, labels=False) + 1)
    m = x.groupby(["date", "q"]).ex.mean().unstack()           # 每月每组超额
    info = S.groupby("date")[["bull", "temp"]].first()
    top, bot = m[q], m[1]
    r = dict(因子=col, 最高组月均超额=top.mean() * 100, 最低组=bot.mean() * 100, 高减低=(top - bot).mean() * 100,
             高减低t=(top - bot).mean() / ((top - bot).std() / np.sqrt(len(m))), 高组跑赢月份=f"{(top > 0).sum()}/{len(m)}",
             前段=(top - bot)[m.index < MID].mean() * 100, 后段=(top - bot)[m.index >= MID].mean() * 100,
             牛=(top - bot)[info.bull.reindex(m.index).to_numpy()].mean() * 100, 熊=(top - bot)[~info.bull.reindex(m.index).to_numpy()].mean() * 100)
    return r, m


rows, mats = [], {}
for c in ["growth", "accel", "roe", "ind_heat", "mom120", "mom20"]:
    r, m = qtab(c); rows.append(r); mats[c] = m
t = pd.DataFrame(rows).round(2)
print(f"====== 单因子，五等分，看之后 {H}（超额 = 组平均 − 全体等权），单位 %")
print(t.to_string(index=False))
print("\n各组月均超额（1=最低 … 5=最高）")
print(pd.DataFrame({k: (v.mean() * 100).round(2) for k, v in mats.items()}).T.to_string())

# 组合：主线里的高成长
def pct_rank(col):
    return S.groupby("date")[col].rank(pct=True)
for c in ["growth", "accel", "ind_heat", "mom120", "roe"]:
    S[c + "_r"] = pct_rank(c)
combos = {
    "高成长(前30%)": S.growth_r >= .7,
    "主线行业(前30%)": S.ind_heat_r >= .7,
    "高成长+主线": (S.growth_r >= .7) & (S.ind_heat_r >= .7),
    "高成长+增速加快": (S.growth_r >= .7) & (S.accel_r >= .7),
    "高成长+主线+强势": (S.growth_r >= .7) & (S.ind_heat_r >= .7) & (S.mom120_r >= .7),
    "高成长+强势": (S.growth_r >= .7) & (S.mom120_r >= .7),
    "强势(前30%)": S.mom120_r >= .7,
    "高成长+弱势(跌多了)": (S.growth_r >= .7) & (S.mom120_r <= .3),
}
info = S.groupby("date")[["bull", "temp"]].first()
rows = []
for k, m in combos.items():
    e = S[m].groupby("date").ex.agg(["mean", "size"])
    e = e.reindex(info.index)
    b = info.bull.to_numpy()
    cold = (info.temp < 40).to_numpy(); hot = (info.temp >= 60).to_numpy()
    rows.append(dict(组合=k, 每月只数=round(e["size"].mean()), 月均超额=e["mean"].mean() * 100, 跑赢月份=f"{(e['mean'] > 0).sum()}/{e['mean'].notna().sum()}",
                     t=e["mean"].mean() / (e["mean"].std() / np.sqrt(e["mean"].notna().sum())),
                     前段=e["mean"][e.index < MID].mean() * 100, 后段=e["mean"][e.index >= MID].mean() * 100,
                     牛=e["mean"][b].mean() * 100, 熊=e["mean"][~b].mean() * 100, 温度低于40=e["mean"][cold].mean() * 100, 温度高于60=e["mean"][hot].mean() * 100))
print(f"\n====== 组合（每月等权买入），之后 {H} 相对全体等权的超额 %")
print(pd.DataFrame(rows).round(2).to_string(index=False))

# 择时：情绪温度 vs 全体等权之后的绝对收益
mk = S.groupby("date")[H].mean() * 100
tb = pd.cut(info.temp, [0, 20, 40, 60, 80, 101], labels=["冰点<20", "偏冷", "中性", "偏热", "过热>80"])
print(f"\n====== 情绪温度（月底）之后 {H} 全体等权平均收益 %")
print(pd.DataFrame({"月份数": mk.groupby(tb, observed=True).size(), "平均": mk.groupby(tb, observed=True).mean().round(2)}).to_string())
