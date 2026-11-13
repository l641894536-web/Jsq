"""A股：高开低走 / 低开收高到底有多常见？（全A，2021-11 → 2026-11 为主，2016-2021 对照）
跳空 gap = 开盘/前收-1；开盘后 oc = 收盘/开盘-1；"比大盘" = oc 减去当天全部股票 oc 的平均。
开盘就涨停/跌停（买不进/卖不出）的单独算，不进分档。
T+1：今天开盘买，最早明天卖 —— 另算 开盘买→明天收盘 (o→c1)。
用法: python3 ashare_gap_bt.py
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apanel

P = apanel.build(); D = apanel.derive(P)
dates, codes, s = D["dates"], D["codes"], D["s"]
T, N = P["open"].shape
op = P["open"].astype("float64"); hi = P["high"].astype("float64"); lo = P["low"].astype("float64")
close, pc, up, dn, ok, age = D["close"], D["pc"], D["up"], D["dn"], D["ok"], D["age"]
with np.errstate(all="ignore"):
    gap = op / pc - 1; oc = close / op - 1; cc = close / pc - 1
# 明天：今天收盘之后的复权衔接用明天的前收（交易所已除权）
nx = lambda m: np.vstack([m[1:], np.full((1, N), np.nan)])
with np.errstate(all="ignore"):
    c1 = nx(close / pc); o1 = nx(op / pc)                 # 明天收盘/明天前收、明天开盘/明天前收
    o2c1 = (close / op) * c1 - 1                          # 今天开盘买 → 明天收盘
    o2o1 = (close / op) * o1 - 1                          # 今天开盘买 → 明天开盘
    c2c1 = c1 - 1
lim_open = (np.abs(op - up) < 0.0051) | (np.abs(op - dn) < 0.0051)
U = ok & (age >= 60) & np.isfinite(gap) & np.isfinite(oc) & (op > 0) & ~lim_open
with np.errstate(all="ignore"):
    mkt_oc = np.nanmean(np.where(U, oc, np.nan), 1)
ocx = oc - mkt_oc[:, None]

per = np.full(T, "", dtype=object)
per[(dates >= "2016-01-01") & (dates < "2021-11-01")] = "2016-21"
per[(dates >= "2021-11-01") & (dates < "2024-05-15")] = "前半"
per[(dates >= "2024-05-15")] = "后半"
P5 = np.isin(per, ["前半", "后半"])

EDGES = [-np.inf, -0.05, -0.03, -0.01, -0.002, 0.002, 0.01, 0.03, 0.05, np.inf]
LAB = ["≤−5%", "−5~−3%", "−3~−1%", "−1~−0.2%", "平开±0.2%", "+0.2~1%", "+1~3%", "+3~5%", "≥+5%"]


def table(mask_rows, title):
    m = U & mask_rows[:, None]
    g = np.digitize(gap[m], EDGES) - 1
    x = pd.DataFrame({"g": g, "oc": oc[m], "ocx": ocx[m], "o2c1": o2c1[m], "c2c1": c2c1[m],
                      "per": np.broadcast_to(per[:, None], (T, N))[m]})
    out = []
    for k, y in x.groupby("g"):
        r = {"跳空": LAB[k], "占比": len(y) / len(x), "开盘后平均": y.oc.mean(), "中位": y.oc.median(), "收在开盘上方": (y.oc > 0).mean(),
             "比大盘": y.ocx.mean(), "开盘买→明天收盘": y.o2c1.mean(), "收盘买→明天收盘": y.c2c1.mean()}
        for p_ in ["前半", "后半", "2016-21"]:
            z = y[y.per == p_]
            if len(z):
                r[p_] = z.oc.mean()
        out.append(r)
    o = pd.DataFrame(out)
    print(f"\n== {title}（{len(x):,} 个股票日）==")
    f = lambda v: f"{v*100:+.2f}%" if isinstance(v, float) else v
    o2 = o.copy()
    for c in o2.columns[1:]:
        o2[c] = o2[c].map(lambda v: f"{v*100:.1f}%" if c in ("占比", "收在开盘上方") else f"{v*100:+.2f}%")
    print(o2.to_string(index=False))
    return o


R = {}
R["all5"] = table(P5, "近5年 全A：按开盘跳空分档，开盘后怎么走")
R["old"] = table(per == "2016-21", "2016-2021 对照")
pd.to_pickle(R, "/home/claude/bt/_gap_tables.pkl")

# 开盘涨停/跌停的那些
m = ok & (age >= 60) & P5[:, None] & (np.abs(op - up) < 0.0051)
print(f"\n开盘就涨停（一字/秒板）{m.sum():,} 次：收盘还在涨停 {np.mean(np.abs(close[m]-up[m])<0.0051):.0%}，平均开盘后 {np.nanmean(oc[m])*100:+.2f}%")

# ---------------- 指数层面：上证、沪深300、创业板指
ix = __import__("market_data.load", fromlist=["load"]) if False else None
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load
I = load.a_share_index(start="2016-01-01")
print("\n== 指数：高开（≥+0.3%）当天收在开盘下方的比例 / 低开（≤−0.3%）收在开盘上方的比例 ==")
for code, nm in [("sh.000001", "上证"), ("sh.000300", "沪深300"), ("sz.399006", "创业板指"), ("sh.000852", "中证1000")]:
    g = I[I.code == code].set_index("date").sort_index()
    g = g[g.open > 0]
    gp = g.open / g.preclose - 1; o_c = g.close / g.open - 1
    for lab, a, b in [("近5年", "2021-11-01", "2026-12-31"), ("2016-21", "2016-01-01", "2021-10-31")]:
        x = pd.DataFrame({"gp": gp, "oc": o_c}).loc[a:b]
        H = x[x.gp >= 0.003]; L_ = x[x.gp <= -0.003]; F = x[x.gp.abs() < 0.003]
        print(f"{nm:6s} {lab}: 高开{len(H)}天 收在开盘下方 {(H.oc<0).mean():.0%} 平均{H.oc.mean()*100:+.2f}% | 低开{len(L_)}天 收在开盘上方 {(L_.oc>0).mean():.0%} 平均{L_.oc.mean()*100:+.2f}% | 平开{len(F)}天 平均{F.oc.mean()*100:+.2f}% | 所有日子开盘后平均 {x.oc.mean()*100:+.3f}%")

# ---------------- 个股特性：高开 2~7%（没开在涨停）/ 低开 −7~−2%
mu = U & (gap >= 0.02) & (gap < 0.07) & P5[:, None]
md = U & (gap <= -0.02) & (gap > -0.07) & P5[:, None]
amt = np.nan_to_num(P["amount"].astype("float64"))
A20 = pd.DataFrame(amt).rolling(20, min_periods=10).mean().shift(1).to_numpy()
VOL = pd.DataFrame(D["pct"]).rolling(20, min_periods=10).std().shift(1).to_numpy()
adj = D["adj"]
with np.errstate(all="ignore"):
    M20 = np.vstack([np.full((21, N), np.nan), adj[20:-1] / adj[:-21] - 1])        # 截至昨天的20日涨幅
TURN = np.vstack([np.full((1, N), np.nan), P["turn"][:-1].astype("float64")])
ZT1 = np.vstack([np.zeros((1, N), bool), D["zt"][:-1]]); STK1 = np.vstack([np.zeros((1, N), np.int16), D["streak"][:-1]])
HI250 = pd.DataFrame(adj).rolling(250, min_periods=200).max().shift(1).to_numpy()
with np.errstate(all="ignore"):
    DD = np.vstack([np.full((1, N), np.nan), adj[:-1]]) / HI250 - 1
board = np.where(np.char.startswith(codes, "sh.68"), "科创板", np.where(np.char.startswith(codes, "sz.30"), "创业板", "主板"))


def qrank(M):
    """每天横截面五分位（1最小…5最大）"""
    with np.errstate(all="ignore"):
        r = pd.DataFrame(M).rank(axis=1, pct=True).to_numpy()
    return np.ceil(r * 5).clip(1, 5)


Q = {"成交额": qrank(A20), "波动": qrank(VOL), "近20日涨幅": qrank(M20), "换手率": qrank(TURN)}


def feats(m):
    ii, jj = np.nonzero(m)
    f = pd.DataFrame({"oc": oc[ii, jj], "ocx": ocx[ii, jj], "o2c1": o2c1[ii, jj], "per": per[ii],
                      "板块": board[jj], "昨天": np.where(STK1[ii, jj] >= 2, "昨天连板", np.where(ZT1[ii, jj], "昨天首板", "昨天没涨停")),
                      "股价": np.where(close[np.maximum(ii - 1, 0), jj] < 5, "5元以下", "5元以上"),
                      "离一年高点": pd.cut(DD[ii, jj], [-1, -0.5, -0.3, -0.1, 0.01], labels=["跌了50%+", "30-50%", "10-30%", "10%以内"]).astype(str),
                      "date": dates[ii], "code": codes[jj]})
    for k, q in Q.items():
        f[k] = q[ii, jj]
    return f


FU, FD = feats(mu), feats(md)
FU.to_pickle("/home/claude/bt/_gap_up.pkl"); FD.to_pickle("/home/claude/bt/_gap_dn.pkl")


def by(F, col, lab):
    g = F.groupby(col)
    t = pd.DataFrame({"次数": g.size(), "开盘后": g.oc.mean(), "收在开盘下方" if lab == "高开" else "收在开盘上方": g.oc.apply(lambda v: ((v < 0) if lab == "高开" else (v > 0)).mean()),
                      "比大盘": g.ocx.mean(), "前半": F[F.per == "前半"].groupby(col).oc.mean(), "后半": F[F.per == "后半"].groupby(col).oc.mean()})
    for c in t.columns[1:]:
        t[c] = t[c].map(lambda v: f"{v*100:+.2f}%" if c != t.columns[2] else f"{v*100:.0f}%")
    return t


for lab, F in [("高开2~7%", FU), ("低开2~7%", FD)]:
    print(f"\n######## {lab}：{len(F):,} 次，开盘后平均 {F.oc.mean()*100:+.2f}%（比大盘 {F.ocx.mean()*100:+.2f}%），开盘买→明天收盘 {F.o2c1.mean()*100:+.2f}%")
    for col in ["板块", "成交额", "波动", "近20日涨幅", "换手率", "昨天", "股价", "离一年高点"]:
        print(f"-- 按{col}（成交额/波动/涨幅/换手 1=最小 5=最大，都用前一天的数）")
        print(by(F, col, lab[:2]).to_string())

# ---------------- 单只股票的"脾气"能不能延续：前半 vs 后半，每只股票高开后比大盘的平均
for lab, F in [("高开", FU), ("低开", FD)]:
    a = F[F.per == "前半"].groupby("code").ocx.agg(["mean", "size"]); b = F[F.per == "后半"].groupby("code").ocx.agg(["mean", "size"])
    j = a.join(b, lsuffix="1", rsuffix="2", how="inner"); j = j[(j.size1 >= 10) & (j.size2 >= 10)]
    j["q"] = pd.qcut(j.mean1, 5, labels=[1, 2, 3, 4, 5])
    print(f"\n== {lab}脾气延续：{len(j)} 只股票（两段都≥10次），前后两段相关 {j.mean1.corr(j.mean2):.2f}（秩相关 {j.mean1.corr(j.mean2, method='spearman'):.2f}）")
    print((j.groupby("q", observed=True)[["mean1", "mean2"]].mean() * 100).round(2).rename(columns={"mean1": "前半段比大盘%", "mean2": "后半段比大盘%"}).to_string())
    j.to_pickle(f"/home/claude/bt/_gap_persist_{lab}.pkl")

# ---------------- 操作上值多少：持仓要卖 / 想买
for lab, F in [("高开2~7%", FU), ("低开2~7%", FD)]:
    print(f"{lab}：开盘卖比收盘卖多拿 {-F.oc.mean()*100:+.2f}%；开盘买比收盘买便宜 {F.oc.mean()*100:+.2f}%（负=开盘买更贵）")
for lab, m in [("低开≤−3%开盘买", U & (gap <= -0.03) & P5[:, None]), ("高开≥+3%开盘买", U & (gap >= 0.03) & P5[:, None]), ("所有日子开盘买", U & P5[:, None])]:
    x = o2c1[m]; y = o2o1[m]
    print(f"{lab}：→明天开盘 {np.nanmean(y)*100:+.2f}%  →明天收盘 {np.nanmean(x)*100:+.2f}%  （{m.sum():,} 次）")
