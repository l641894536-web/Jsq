import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
import turtle_bt as TB
res, D = pickle.load(open("/home/claude/bt/turtle_res.pkl", "rb"))
pd.set_option("display.width", 220)
def line(nm, C, T=None):
    s = TB.stats(C); h1, h2 = TB.halves(C)
    print(f"{nm:<34} 年化 {s['cagr']*100:+6.1f}%  最大回撤 {s['mdd']*100:6.1f}%  夏普 {s['sharpe']:.2f}  前段 {h1*100:+6.1f}%  后段 {h2*100:+6.1f}%" + (f"  {len(T)}笔" if T is not None else ""))
print("== 风险缩小（每1N亏账户的x%）")
for risk in (0.0025, 0.005):
    for (eL, xL, mode, nm) in [(55, 20, "regime_long", "系统2 只在200日线上做多"), (55, 20, "long", "系统2 只做多"), (20, 10, "regime_long", "系统1 只在200日线上做多")]:
        C, T = TB.run(D, eL, xL, mode, risk=risk); line(f"{nm} 风险{risk*100:.2f}%", C, T)
print("\n== 随机进场对照（系统2出场/仓位/加仓完全一样，只在200日线上做多，30次）")
C0, T0 = TB.run(D, 55, 20, "regime_long", risk=0.005); n0 = len(T0)
for p in (0.01, 0.02, 0.04):
    rs = []
    for seed in range(30):
        TB_p = None
        C, T = TB.run(D, 55, 20, "regime_long", risk=0.005, rand=np.random.default_rng(seed))
        rs.append((TB.stats(C)["cagr"], TB.stats(C)["mdd"], len(T)))
    break
a = np.array(rs); print(f"真信号：年化 {TB.stats(C0)['cagr']*100:+.1f}% 回撤 {TB.stats(C0)['mdd']*100:.1f}% {n0}笔；随机：年化中位 {np.median(a[:,0])*100:+.1f}%（10%~90%: {np.percentile(a[:,0],10)*100:+.1f}%~{np.percentile(a[:,0],90)*100:+.1f}%），回撤中位 {np.median(a[:,1])*100:.1f}%，笔数中位 {np.median(a[:,2]):.0f}；真信号胜过 {(a[:,0] < TB.stats(C0)['cagr']).mean()*100:.0f}% 的随机")
