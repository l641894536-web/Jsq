import numpy as np, pandas as pd
X = pd.read_pickle("/home/claude/bt/_intraday_X.pkl")
NAMES = {"sz.002463": "沪电股份", "sh.601138": "工业富联", "sh.512760": "半导体ETF(国泰)"}
pct = lambda v: f"{v*100:+.2f}%"
COST = np.where(X.code.str.startswith("sh.51") | X.code.str.startswith("sh.58"), 0.0002, 0.001)
X["cost"] = COST
# 高开：等15分钟再决定
def rule_c(D):
    up = D.p945 > D.O
    return np.where(up, D.C, D.p945)
def rule_d(D):   # 9:45 在开盘上方就拿，之后跌破开盘15分钟低点再卖（否则收盘）；在下方就9:45卖
    up = D.p945 > D.O
    return np.where(up, D.s_or, D.p945)
print("== 高开：开盘15分钟后再决定（结果=卖价比开盘价高多少）==")
for thr in (0.01, 0.02, 0.03):
    D = X[(X.gap >= thr) & (X.gap < 0.095)]
    for lab, s in [("开盘卖", D.O), ("收盘卖", D.C), ("9:45在开盘下方就9:45卖，上方拿到收盘", rule_c(D)), ("9:45在开盘下方就卖，上方拿着、跌破开盘15分钟低点再卖", rule_d(D))]:
        x = pd.Series(np.asarray(s) / D.O.to_numpy() - 1, index=D.index)
        print(f"高开≥{thr*100:.0f}% {lab:34s} {pct(x.mean())} 前后 {pct(x[D.per=='前半'].mean())}/{pct(x[D.per=='后半'].mean())} 你的3只 {pct(x[D.mine].mean())} 最差10% {pct(x.quantile(.1))}")
# 基线：所有日子，开盘15分钟方向和之后
X["rest"] = X.C / X.p945 - 1
for lab, D in [("高开≥2%", X[(X.gap >= 0.02) & (X.gap < 0.095)]), ("平开±0.5%", X[X.gap.abs() < 0.005]), ("低开≥2%", X[(X.gap <= -0.02) & (X.gap > -0.095)])]:
    a, b = D[D.p945 > D.O], D[D.p945 <= D.O]
    print(f"{lab:8s} 9:45在开盘上方 → 之后到收盘 {pct(a.rest.mean())}（{len(a)}天，前后 {pct(a[a.per=='前半'].rest.mean())}/{pct(a[a.per=='后半'].rest.mean())}）；下方 → {pct(b.rest.mean())}（前后 {pct(b[b.per=='前半'].rest.mean())}/{pct(b[b.per=='后半'].rest.mean())}）")
print("\n== 低开做T：开盘先买（用底仓，当天卖掉同样数量）==")
for thr in (0.01, 0.02, 0.03):
    D = X[(X.gap <= -thr) & (X.gap > -0.095)]
    r_close = D.C / D.O - 1 - D.cost
    # 冲到开盘价+1.5%就卖，否则收盘
    tgt = np.where(D.H >= D.O * 1.015, 0.015, D.C / D.O - 1) - D.cost
    # 9:45 在开盘上方才买（9:45买），收盘卖
    m = D.p945 > D.O
    r945 = (D.C / D.p945 - 1 - D.cost)[m]
    print(f"低开≥{thr*100:.0f}% {len(D)}天：开盘买收盘卖 {pct(r_close.mean())} 赢{(r_close>0).mean():.0%} 前后 {pct(r_close[D.per=='前半'].mean())}/{pct(r_close[D.per=='后半'].mean())} 你的3只 {pct(r_close[D.mine].mean())}"
          f" | 开盘买、涨1.5%卖 {pct(tgt.mean())} 赢{(tgt>0).mean():.0%} 前后 {pct(tgt[D.per=='前半'].mean())}/{pct(tgt[D.per=='后半'].mean())}"
          f" | 9:45站上开盘才买、收盘卖 {pct(r945.mean())}（{m.sum()}天）")
print("\n== 你的3只 ==")
for c, n in NAMES.items():
    D = X[X.code == c]
    hh = D[(D.gap >= 0.02) & (D.gap < 0.095)]; ll = D[(D.gap <= -0.02) & (D.gap > -0.095)]
    if not len(D): continue
    up = hh.p945 > hh.O
    print(f"{n}：{len(D)}天；高开≥2% {len(hh)}天，其中9:45还在开盘上方 {up.mean():.0%}，这些之后到收盘 {pct((hh.C/hh.p945-1)[up].mean())}；在下方的之后 {pct((hh.C/hh.p945-1)[~up].mean())}；"
          f"低开≥2% {len(ll)}天，开盘买收盘卖 {pct((ll.C/ll.O-1-ll.cost).mean())}")
    print("   高开≥2%的最高价时间：", (pd.cut(hh.t_hi.str.slice(0,4).astype(int), [0,945,1000,1030,1130,1400,1500], labels=["9:45前","9:45-10","10-10:30","10:30-11:30","13-14","14-15"]).value_counts(normalize=True).sort_index()*100).round(0).to_dict())
