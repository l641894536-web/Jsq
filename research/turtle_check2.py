import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
import turtle_bt as TB
res, D = pickle.load(open("/home/claude/bt/turtle_res.pkl", "rb"))
C0, T0 = TB.run(D, 55, 20, "regime_long", risk=0.005); s0 = TB.stats(C0)
for p in (0.03, 0.05):
    a = np.array([[TB.stats(C)["cagr"], TB.stats(C)["mdd"], len(T)] for C, T in (TB.run(D, 55, 20, "regime_long", risk=0.005, rand=np.random.default_rng(seed), p_rand=p) for seed in range(30))])
    print(f"随机 p={p}: 年化中位 {np.median(a[:,0])*100:+.1f}%（10~90分位 {np.percentile(a[:,0],10)*100:+.1f}%~{np.percentile(a[:,0],90)*100:+.1f}%）回撤中位 {np.median(a[:,1])*100:.1f}% 笔数中位 {np.median(a[:,2]):.0f}；真信号 {s0['cagr']*100:+.1f}% 胜过 {(a[:,0] < s0['cagr']).mean()*100:.0f}%")
yr = C0.resample("YE").last(); y = yr.pct_change(); y.iloc[0] = yr.iloc[0] / C0.iloc[0] - 1
print("系统2只在200日线上做多 风险0.5% 每年:", " ".join(f"{k.year}:{v*100:+.0f}%" for k, v in y.items()))
# 各品种贡献
T0["grp"] = T0.sym.map(TB.GROUP)
g = T0.groupby("sym").agg(笔数=("pnl", "size"), 赚的比例=("pnl", lambda x: round((x > 0).mean() * 100)), 合计=("pnl", "sum")).sort_values("合计", ascending=False)
g["合计"] = (g["合计"] * 100).round(1); print("\n各品种对组合的贡献（占初始本金%，复利前）:\n", g.T.to_string())
# 每个品种单独做
print("\n每个品种单独用这套（只在自身200日线上做多，风险0.5%/N）:")
rows = []
for s in D:
    C, T = TB.run(D, 55, 20, "regime_long", risk=0.005, syms=[s]); st = TB.stats(C); h1, h2 = TB.halves(C)
    rows.append(dict(品种=TB.NAME[s], 年化=round(st["cagr"]*100, 1), 回撤=round(st["mdd"]*100, 1), 前段=round(h1*100, 1), 后段=round(h2*100, 1), 笔数=len(T), 赚的比例=round((T.pnl > 0).mean()*100) if len(T) else 0))
print(pd.DataFrame(rows).sort_values("年化", ascending=False).to_string(index=False))
# 买入持有对照：等权（每月再平衡）全部持有 / 只在200日线上持有
px = pd.DataFrame({s: D[s].close for s in D}).loc[TB.START:TB.END].ffill()
ma = pd.DataFrame({s: D[s].ma200 for s in D}).reindex(px.index).ffill()
ret = px.pct_change().fillna(0)
bh = (1 + ret.mean(1)).cumprod(); print("\n等权买入持有全部16个:", {k: round(v*100, 1) if isinstance(v, float) else v for k, v in TB.stats(bh).items()}, "前后段", [round(x*100, 1) for x in TB.halves(bh)])
w = (px.shift(1) > ma.shift(1)).astype(float); f = (ret * w).sum(1) / 16
tf = (1 + f).cumprod(); print("只在200日线上方时等权持有:", {k: round(v*100, 1) if isinstance(v, float) else v for k, v in TB.stats(tf).items()}, "前后段", [round(x*100, 1) for x in TB.halves(tf)])
