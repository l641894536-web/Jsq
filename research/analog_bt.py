"""历史相似行情（类比法）回测。
每天的"行情状态" = 6 个数：离200日线、离50日线、20日涨幅、60日涨幅、波动相对水平（20日波动/过去一年中位）、离52周高点。
对每个检验日 t：只在 t 之前、且之后 H 天已经走完的日子里找最像的 20 天（标准化后欧氏距离，彼此至少隔 5 个交易日），
用它们之后 H 天的涨跌预测 t 之后 H 天：
  方向：20 段里涨的比例、平均涨幅
  范围：20 段之后 H 天涨跌幅的 10%–90% 区间
检验 2021-11 → 2026-10，每天都算；显著性用不重叠的样本（每 H 天取一个）。
对照：方向只看 200 日线（牛/熊）；范围只按当前 20 日波动推算。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
from scipy.stats import spearmanr

E0, MID, E1 = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-01"), pd.Timestamp("2026-11-01")
K, GAP = 20, 5
FEATS = ["dma200", "dma50", "r20", "r60", "volrel", "dd252"]


def features(close):
    c = close.dropna()
    ret = c.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    f = pd.DataFrame({
        "dma200": c / c.rolling(200).mean() - 1,
        "dma50": c / c.rolling(50).mean() - 1,
        "r20": c / c.shift(20) - 1,
        "r60": c / c.shift(60) - 1,
        "volrel": np.log(vol20 / vol20.rolling(250).median()),
        "dd252": c / c.rolling(252).max() - 1,
        "vol20": vol20,
    })
    for h in (5, 20):
        f[f"f{h}"] = c.shift(-h) / c - 1
    return f.dropna(subset=FEATS)


def analog(f, H):
    X = f[FEATS].to_numpy(float); fw = f[f"f{H}"].to_numpy(float)
    dates = f.index
    rows = []
    for t in np.where((dates >= E0) & (dates < E1))[0]:
        pool = np.arange(0, t - H)               # 之后 H 天已经走完
        pool = pool[np.isfinite(fw[pool])]
        if len(pool) < 500 or not np.isfinite(fw[t]):
            continue
        mu, sd = X[pool].mean(0), X[pool].std(0) + 1e-12
        d = np.sqrt((((X[pool] - X[t]) / sd) ** 2).sum(1))
        order = pool[np.argsort(d)]
        pick = []
        for i in order:
            if all(abs(i - j) >= GAP for j in pick):
                pick.append(i)
                if len(pick) == K:
                    break
        y = fw[pick]
        rows.append(dict(date=dates[t], real=fw[t], up=(y > 0).mean(), mean=y.mean(), med=np.median(y),
                         p10=np.quantile(y, .1), p90=np.quantile(y, .9), sd=y.std(),
                         naive_sd=f.vol20.iloc[t] * np.sqrt(H / 252), bull=X[t, 0] > 0,
                         dist=float(np.sort(d)[K - 1]), first=str(dates[pick[0]].date())))
    return pd.DataFrame(rows)


def evaluate(a, name, H):
    a = a.copy()
    a["half"] = np.where(a.date < MID, "前半", "后半")
    nono = a.iloc[::H]
    ic_all = spearmanr(a["mean"], a.real).statistic
    ic_n = spearmanr(nono["mean"], nono.real)
    a["信号"] = np.where(a.up >= .65, "偏涨(≥65%)", np.where(a.up <= .35, "偏跌(≤35%)", "中间"))
    t = a.groupby("信号").real.agg(天数="size", 之后平均=lambda x: round(x.mean() * 100, 2), 涨的比例=lambda x: round((x > 0).mean() * 100))
    t = t.join(a.groupby(["信号", "half"]).real.mean().unstack().mul(100).round(2))
    base = (a.real > 0).mean() * 100
    # 在牛/熊里面再分：类比能不能比200日线多给信息
    w = a.groupby(["bull", "信号"]).real.agg(["size", lambda x: round(x.mean() * 100, 2), lambda x: round((x > 0).mean() * 100)])
    w.columns = ["天数", "之后平均%", "涨的比例%"]
    # 范围
    absr = a.real.abs()
    rc_an = spearmanr(a.sd, absr).statistic; rc_nv = spearmanr(a.naive_sd, absr).statistic
    inside = ((a.real >= a.p10) & (a.real <= a.p90)).mean() * 100
    nv_in = (absr <= 1.2816 * a.naive_sd).mean() * 100
    print(f"\n=========== {name} · 之后{H}天 · {len(a)}天（不重叠 {len(nono)}）")
    print(f"方向：类比平均涨幅 vs 实际 秩相关 {ic_all:.3f}（不重叠 {ic_n.statistic:.3f}，p={ic_n.pvalue:.2f}）；平时涨的比例 {base:.0f}%")
    print(t.to_string())
    print("按200日线牛熊再分："); print(w.to_string())
    print(f"范围：类比波动 vs 实际涨跌幅大小 秩相关 {rc_an:.3f}，只看当前波动 {rc_nv:.3f}；实际落在类比10–90%区间 {inside:.0f}%（应≈80%），按当前波动推算的同一区间 {nv_in:.0f}%")
    return dict(name=name, H=H, ic=ic_all, ic_n=ic_n.statistic, p=ic_n.pvalue, rc_an=rc_an, rc_nv=rc_nv, inside=inside, nv_in=nv_in)


if __name__ == "__main__":
    d = load.us_daily(["GC=F", "SI=F", "^NDX", "^GSPC", "AMD", "MU", "HG=F"])
    px = d.pivot(index="date", columns="ticker", values="close")
    ai = load.a_share_index()
    ai["date"] = pd.to_datetime(ai.date)
    print(ai.code.unique())
    series = {"黄金": px["GC=F"], "白银": px["SI=F"], "纳指": px["^NDX"], "标普": px["^GSPC"], "AMD": px["AMD"], "美光": px["MU"], "铜": px["HG=F"]}
    for code, nm in [("sh.000001", "上证"), ("sh.000300", "沪深300")]:
        s = ai[ai.code == code].set_index("date").close
        if len(s):
            series[nm] = s
    res = []
    for nm, s in series.items():
        f = features(s)
        for H in (5, 20):
            a = analog(f, H)
            a.to_csv(f"analog_{nm}_{H}.csv", index=False)
            res.append(evaluate(a, nm, H))
    print("\n\n######## 汇总")
    print(pd.DataFrame(res).round(3).to_string(index=False))
