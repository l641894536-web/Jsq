"""黄金 × 美元 × 美债利率：美元/利率的强弱能不能当黄金的买卖依据？（2026-11-17 定稿后才跑；只测黄金，不混别的品种）
数据：GC=F（纽约金期货日线）、UUP（美元ETF）、^TNX（10年美债利率）、有的话加 TIP（通胀保值债ETF，涨=实际利率降）和 DX-Y.NYB（美元指数）。
状态（收盘时能知道）：某项收盘在自己50日均线 上/下。"顺风" = 美元在50日线下、利率在50日线下、（TIP在50日线上）。
A. 状态 → 之后 20/60 个交易日黄金涨跌（每10天取一次样；前后两段分开：2020-09→2023-09、2023-10→现在）。
B. 做法对比（收盘出信号 → 第二天开盘成交，按开盘到开盘算收益；每次进出各扣0.1%）：
   S0 一直拿着；S1 金在自己50日线上才拿（交易台黄金规则的日线近似）；S2 = S1 且美元顺风；S3 = S1 且利率顺风；S4 = S1 且两个都顺风；S5 只看两个都顺风（不看金自己）。
   每个做法另和"一直拿着但只拿同样比例"比（风险少是因为拿得少，还是因为挑对了时候）。
"""
import os, sys
import numpy as np, pandas as pd
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from market_data import load

pct = lambda v: "—" if v is None or not np.isfinite(v) else f"{v*100:+.1f}%"
COST = 0.001
d = load.us_daily(["GC=F", "UUP", "^TNX", "TIP", "DX-Y.NYB"], start="2020-01-01")
C = d.pivot(index="date", columns="ticker", values="adj_close").sort_index(); O = d.pivot(index="date", columns="ticker", values="open").sort_index()
C = C[C["GC=F"].notna()].ffill(limit=3); O = O.reindex(C.index)
usd = "DX-Y.NYB" if "DX-Y.NYB" in C and C["DX-Y.NYB"].notna().sum() > 800 else "UUP"
has_tip = "TIP" in C and C["TIP"].notna().sum() > 800
print(f"数据 {C.index[0].date()} → {C.index[-1].date()}；美元用 {usd}；实际利率代理 TIP：{'有' if has_tip else '没有'}")
ma = lambda s: s.rolling(50).mean()
g = C["GC=F"]; S = pd.DataFrame(index=C.index)
S["gold_up"] = g > ma(g); S["usd_dn"] = C[usd] < ma(C[usd]); S["rate_dn"] = C["^TNX"] < ma(C["^TNX"])
if has_tip: S["real_dn"] = C["TIP"] > ma(C["TIP"])
S = S[ma(g).notna() & ma(C[usd]).notna() & ma(C["^TNX"]).notna()]
S["tail"] = S.usd_dn.astype(int) + S.rate_dn.astype(int)
for H in (20, 60): S[f"f{H}"] = g.shift(-H) / g - 1
S["half"] = np.where(S.index < "2023-10-01", "前半", "后半")

print("\n== A. 当天状态 → 之后黄金涨跌（每10天取样）")
X = S.iloc[::10]; X = X[X.f20.notna()]
print(f"全部 {len(X)} 次：20天 {pct(X.f20.mean())}，60天 {pct(X.f60.mean())}")
def tab(col, names):
    rows = []
    for k, x in X.groupby(col):
        r = {"状态": names.get(k, k), "次数": len(x), "20天": pct(x.f20.mean()), "60天": pct(x.f60.mean()), "60天上涨": f"{(x.f60 > 0).mean():.0%}"}
        for h in ("前半", "后半"):
            y = x[x.half == h]; r[h + " 60天(n)"] = f"{pct(y.f60.mean())}({len(y)})"
        rows.append(r)
    print(pd.DataFrame(rows).to_string(index=False))
tab("usd_dn", {True: "美元在50日线下(顺风)", False: "美元在50日线上(逆风)"})
tab("rate_dn", {True: "利率在50日线下(顺风)", False: "利率在50日线上(逆风)"})
if has_tip: tab("real_dn", {True: "实际利率降(TIP在线上,顺风)", False: "实际利率升(逆风)"})
tab("tail", {0: "两个都逆风", 1: "一顺一逆", 2: "两个都顺风"})
tab("gold_up", {True: "金在自己50日线上", False: "金在自己50日线下"})

print("\n== B. 做法对比（次日开盘成交，进出各0.1%）")
o = O["GC=F"].reindex(S.index); r = (o.shift(-2) / o.shift(-1) - 1)        # t 收盘决定 → t+1 开盘进 → t+2 开盘的收益
rules = {"S0 一直拿着": pd.Series(True, index=S.index), "S1 金在50日线上": S.gold_up, "S2 S1+美元顺风": S.gold_up & S.usd_dn, "S3 S1+利率顺风": S.gold_up & S.rate_dn,
         "S4 S1+两个都顺风": S.gold_up & S.usd_dn & S.rate_dn, "S5 只看两个都顺风": S.usd_dn & S.rate_dn}
if has_tip: rules["S6 S1+实际利率降"] = S.gold_up & S.real_dn
def stats(pos, rr):
    p = pos.astype(float); sw = p.diff().abs().fillna(p.iloc[0]); net = p * rr - sw * COST; net = net.dropna()
    eq = (1 + net).cumprod(); yrs = len(net) / 252
    return eq.iloc[-1] - 1, eq.iloc[-1] ** (1 / yrs) - 1, (eq / eq.cummax() - 1).min(), p.mean(), sw.sum() / 2
def static(w, rr):
    net = (w * rr).dropna(); eq = (1 + net).cumprod(); yrs = len(net) / 252
    return eq.iloc[-1] ** (1 / yrs) - 1, (eq / eq.cummax() - 1).min()
for lab, m in [("全部", S.index == S.index), ("前半 2020-09→2023-09", S.half == "前半"), ("后半 2023-10→现在", S.half == "后半")]:
    rr = r[m]; rows = []
    for nm, pos in rules.items():
        tot, ann, mdd, w, n = stats(pos[m], rr); sa, sm = static(w, rr)
        rows.append({"做法": nm, "总收益": pct(tot), "年化": pct(ann), "最大回撤": pct(mdd), "持仓时间": f"{w:.0%}", "进出次数": f"{n:.0f}",
                     "同比例一直拿:年化": pct(sa), "同比例:回撤": pct(sm), "年化差": pct(ann - sa)})
    print(f"\n{lab}"); print(pd.DataFrame(rows).to_string(index=False))
L = S.iloc[-1]; print(f"\n现在（{S.index[-1].date()}）：金在50日线{'上' if L.gold_up else '下'}，美元{'顺风' if L.usd_dn else '逆风'}，利率{'顺风' if L.rate_dn else '逆风'}" + (f"，实际利率{'顺风' if L.real_dn else '逆风'}" if has_tip else ""))
