"""A股短线情绪周期：用情绪温度（同工作台）和它5天的变化分6个阶段，看每个阶段之后：
  第二天：全A等权跳空/开盘后、高开股和低开股开盘后、今天涨停的票明天表现（打板次日）
  之后 1/5/20 天：全A等权涨跌（从今天收盘算）
阶段（今天收盘时就知道）：冰点 t<20；高潮 t≥80；低位回升 20≤t<50 且高于前5天平均；低位回落 20≤t<50 且不高于前5天平均；
  中高位升温 50≤t<80 且高于前5天平均；中高位退潮 50≤t<80 且不高于前5天平均。
近5年为主（2021-11 → 2026-11，前后两段），2016-2021 对照；牛熊按全A等权200日线（同工作台）。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apanel

P = apanel.build(); D = apanel.derive(P)
dates, s = D["dates"], D["s"].copy()
T, N = P["open"].shape
op = P["open"].astype("float64"); close, pc, up, dn, ok, age = D["close"], D["pc"], D["up"], D["dn"], D["ok"], D["age"]
with np.errstate(all="ignore"):
    gap = op / pc - 1; oc = close / op - 1; cc = close / pc - 1
lim_open = (np.abs(op - up) < 0.0051) | (np.abs(op - dn) < 0.0051)
U = ok & (age >= 60) & np.isfinite(gap) & np.isfinite(oc) & (op > 0) & ~lim_open
nanm = lambda M, m: np.nanmean(np.where(m, M, np.nan), 1)
with np.errstate(all="ignore"):
    day = pd.DataFrame({
        "ew_gap": nanm(gap, U), "ew_oc": nanm(oc, U),
        "hi_oc": nanm(oc, U & (gap >= 0.02) & (gap < 0.07)), "lo_oc": nanm(oc, U & (gap <= -0.02) & (gap > -0.07)),
        "hi_x": nanm(oc, U & (gap >= 0.02) & (gap < 0.07)) - nanm(oc, U), "lo_x": nanm(oc, U & (gap <= -0.02) & (gap > -0.07)) - nanm(oc, U),
        "hi_fade": nanm((oc < 0).astype(float), U & (gap >= 0.02) & (gap < 0.07)),
    }, index=dates)
# 今天涨停的票明天：跳空、开盘后、全天
ztm = D["zt"]
nx = lambda v: np.concatenate([v[1:], [np.nan]])
zt_next_gap = np.full(T, np.nan); zt_next_oc = np.full(T, np.nan); zt_next_cc = np.full(T, np.nan); zt2_next_cc = np.full(T, np.nan)
for t in range(T - 1):
    m = ztm[t] & ok[t + 1] & np.isfinite(op[t + 1])
    if m.sum():
        zt_next_gap[t] = np.nanmean(gap[t + 1, m]); zt_next_oc[t] = np.nanmean(oc[t + 1, m]); zt_next_cc[t] = np.nanmean(cc[t + 1, m])
    m2 = m & (D["streak"][t] >= 2)
    if m2.sum():
        zt2_next_cc[t] = np.nanmean(cc[t + 1, m2])
s = s.join(day)
s["zt_gap1"], s["zt_oc1"], s["zt_cc1"], s["zt2_cc1"] = zt_next_gap, zt_next_oc, zt_next_cc, zt2_next_cc
for k in ["ew_gap", "ew_oc", "hi_oc", "lo_oc", "hi_x", "lo_x", "hi_fade"]:
    s[k + "1"] = s[k].shift(-1)                       # 明天的
ix = s["等权指数"]
for h in (1, 5, 20):
    s[f"f{h}"] = ix.shift(-h) / ix - 1
t = s["温度"]; d5 = t - t.shift(1).rolling(5).mean()
ph = np.select([t < 20, t >= 80, (t < 50) & (d5 > 0), t < 50, d5 > 0], ["冰点", "高潮", "低位回升", "低位回落", "中高位升温"], "中高位退潮")
s["阶段"] = np.where(t.isna(), None, ph)
s["期"] = np.select([s.index < "2021-11-01", s.index < "2024-05-15"], ["2016-21", "前半"], "后半")
s.loc[s.index < "2016-01-01", "期"] = None
s.to_pickle("/home/claude/bt/_cycle_s.pkl")

ORDER = ["冰点", "低位回升", "中高位升温", "高潮", "中高位退潮", "低位回落"]
w = s[s["期"].isin(["前半", "后半"])].dropna(subset=["阶段"])
o = s[s["期"] == "2016-21"].dropna(subset=["阶段"])
pct = lambda v: f"{v*100:+.2f}%"


def tab(x, cols):
    g = x.groupby("阶段")
    r = pd.DataFrame({"天数": g.size()}).reindex(ORDER)
    for c, lab in cols:
        r[lab] = g[c].mean().reindex(ORDER).map(pct)
    return r


print(f"近5年 {len(w)} 天，阶段天数占比：", (w["阶段"].value_counts(normalize=True).reindex(ORDER) * 100).round(0).to_dict())
print("\n== 今天在这个阶段 → 明天开盘 ==")
print(tab(w, [("ew_gap1", "明天全A跳空"), ("ew_oc1", "明天开盘后"), ("hi_x1", "高开股比大盘"), ("lo_x1", "低开股比大盘"), ("hi_fade1", "高开股收在开盘下方")]).assign(
    **{"高开股收在开盘下方": lambda r: r["高开股收在开盘下方"].str.replace("+", "").str.replace(".00%", "%")}).to_string())
print("\n== 今天涨停的票，明天（打板次日）==")
print(tab(w, [("zt_gap1", "明天跳空"), ("zt_oc1", "明天开盘后"), ("zt_cc1", "明天全天"), ("zt2_cc1", "连板股明天全天")]).to_string())
print("\n== 之后全A等权涨跌（从今天收盘算）==")
print(tab(w, [("f1", "1天"), ("f5", "5天"), ("f20", "20天")]).to_string())
for p_ in ["前半", "后半"]:
    print(f"-- {p_}:")
    print(tab(w[w["期"] == p_], [("f5", "5天"), ("f20", "20天"), ("hi_x1", "明天高开股比大盘"), ("lo_x1", "明天低开股比大盘"), ("zt_cc1", "涨停次日全天")]).to_string())
print("-- 2016-21 对照:")
print(tab(o, [("f5", "5天"), ("f20", "20天"), ("hi_x1", "明天高开股比大盘"), ("lo_x1", "明天低开股比大盘"), ("zt_cc1", "涨停次日全天")]).to_string())
for rg, lab in [(True, "牛市"), (False, "熊市")]:
    x = w[w["牛"] == rg]
    print(f"-- 近5年 {lab}（{len(x)}天）:")
    print(tab(x, [("f5", "5天"), ("f20", "20天"), ("zt_cc1", "涨停次日全天"), ("lo_x1", "明天低开股比大盘")]).to_string())

# 全A等权（整个市场）层面的高开低走：明天全A平均跳空≥+0.5% 时，开盘后平均
print("\n== 整个市场高开（全A平均跳空≥+0.5%）那天，开盘后 ==")
for p_, x in [("近5年", w), ("2016-21", o)]:
    y = x.dropna(subset=["ew_gap1"]); H = y[y.ew_gap1 >= 0.005]; L_ = y[y.ew_gap1 <= -0.005]
    print(f"{p_}: 高开{len(H)}天 开盘后平均 {H.ew_oc1.mean()*100:+.2f}%，收在开盘下方 {(H.ew_oc1<0).mean():.0%} | 低开{len(L_)}天 开盘后平均 {L_.ew_oc1.mean()*100:+.2f}%，收在开盘上方 {(L_.ew_oc1>0).mean():.0%}")
    for ph_ in ORDER:
        z = H[H["阶段"] == ph_]; z2 = L_[L_["阶段"] == ph_]
        print(f"   {ph_:6s} 高开{len(z):3d}天 开盘后 {z.ew_oc1.mean()*100:+.2f}% 低走{(z.ew_oc1<0).mean():.0%} | 低开{len(z2):3d}天 开盘后 {z2.ew_oc1.mean()*100:+.2f}% 收高{(z2.ew_oc1>0).mean():.0%}")

# 阶段之间怎么转：今天的阶段 → 5天后的阶段
print("\n== 阶段转换（近5年，今天 → 5个交易日后，行和=100%）==")
tr = pd.crosstab(w["阶段"], w["阶段"].shift(-5), normalize="index").reindex(index=ORDER, columns=ORDER)
print((tr * 100).round(0).to_string())
# 每段平均持续天数
seg = (w["阶段"] != w["阶段"].shift()).cumsum()
dur = w.groupby(seg).agg(ph=("阶段", "first"), n=("阶段", "size"))
print("\n每个阶段平均连续几天：", dur.groupby("ph").n.mean().reindex(ORDER).round(1).to_dict())
print("\n最近15天：")
print(s[["温度", "阶段", "涨停", "跌停", "炸板率", "连板高度", "昨日涨停今日涨幅"]].tail(15).round(2).to_string())
