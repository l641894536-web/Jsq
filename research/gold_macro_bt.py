"""黄金白银：加上美元和利率会不会更好？
一、现行规则（1小时突破，出场F，2021-11~2026-10，exit_trades.csv 里 v=F 的金银单子，多空都有）按"美元/利率"分组看成绩。
二、拉长到2006年（日线，COMEX期货 GC=F / SI=F），把2013-2015年的黄金熊市也算进来：
    日线突破20天高点做多 / 跌破20天低点做空，止损2倍ATR，收盘跌破10天低点（做空=涨破10天高点）或40天走；
    按"自身200日线 / 美元（美元指数在50日线上下）/ 利率（10年期美债收益率在50日线上下）"分组。
美元、利率、均线都用前一天收盘，不偷看。成本往返0.1%。单位：100U开5倍每次赚亏多少U（1小时那部分用R：1R=一个止损的钱）。
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq")
from market_data import load

U = load.us_daily(["GC=F", "SI=F", "DX-Y.NYB", "^TNX"], start="2004-01-01")
C = U.pivot(index="date", columns="ticker", values="close").sort_index().ffill()
lag = lambda s, n: (s > s.rolling(n).mean()).shift(1)
REG = pd.DataFrame({"usd_up": lag(C["DX-Y.NYB"], 50), "yld_up": lag(C["^TNX"], 50)})
REG["usd20"] = (C["DX-Y.NYB"] / C["DX-Y.NYB"].shift(20) - 1).shift(1)
REG["yld20"] = (C["^TNX"] - C["^TNX"].shift(20)).shift(1)


def macro_lbl(r):
    if pd.isna(r.usd_up) or pd.isna(r.yld_up): return None
    return ("美元涨" if r.usd_up else "美元跌") + "·" + ("利率升" if r.yld_up else "利率降")


REG["m"] = REG.apply(macro_lbl, axis=1)
pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200)

# ---------------- 一、现行1小时规则按宏观分组
E = pd.read_csv("exit_trades.csv")
E = E[(E.v == "F") & E.grp.isin(["黄金", "白银"])].copy()
E["d"] = pd.to_datetime(E.ts, utc=True).dt.tz_localize(None).dt.normalize()
E = E.join(REG[["m", "usd_up", "yld_up"]], on="d")


def s1(g):
    return pd.Series({"笔": len(g), "平均R": round(g.r.mean(), 2), "胜%": round((g.r > 0).mean() * 100), "前段": round(g[g.half == "h1"].r.mean(), 2), "后段": round(g[g.half == "h2"].r.mean(), 2)})


print("== 一、现行1小时突破规则（2021-11~2026-10），按自身200日线牛熊 × 美元/利率 ==")
print(E.groupby(["grp", "env", "dir", "m"]).apply(s1).to_string())
print("\n只按美元分："); print(E.groupby(["grp", "dir", "usd_up"]).apply(s1).to_string())

# ---------------- 二、日线长历史
def atr(h, l, c, n=20):
    pc = c.shift(1); tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1); return tr.rolling(n).mean()


rows = []
for tk, nm in (("GC=F", "黄金"), ("SI=F", "白银")):
    d = U[U.ticker == tk].set_index("date")[["open", "high", "low", "close"]].sort_index().dropna()
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(d.high, d.low, d.close).to_numpy()
    hi20, lo20 = d.high.rolling(20).max().shift(1).to_numpy(), d.low.rolling(20).min().shift(1).to_numpy()
    hi10, lo10 = d.low.rolling(10).min().to_numpy(), d.high.rolling(10).max().to_numpy()
    own200 = lag(d.close, 200).to_numpy(); own50 = lag(d.close, 50).to_numpy()
    idx = d.index
    for side in (1, -1):
        sig = (c > hi20) if side == 1 else (c < lo20)
        busy = -1
        for i in np.flatnonzero(sig):
            if i <= busy or i < 210 or not np.isfinite(a[i]): continue
            stop = c[i] - side * 2 * a[i]; j_end, px = None, None
            for j in range(i + 1, min(len(c), i + 41)):
                if (side == 1 and l[j] <= stop) or (side == -1 and h[j] >= stop):
                    px = o[j] if (side == 1 and o[j] < stop) or (side == -1 and o[j] > stop) else stop; j_end = j; break
                if (side == 1 and c[j] < hi10[j - 1]) or (side == -1 and c[j] > lo10[j - 1]):
                    px = c[j]; j_end = j; break
            if j_end is None: j_end = min(len(c) - 1, i + 40); px = c[j_end]
            busy = j_end
            ret = side * (px / c[i] - 1) - 0.001
            r = REG.reindex([idx[i]]).iloc[0]
            rows.append((nm, "多" if side == 1 else "空", idx[i], bool(own200[i]), bool(own50[i]), r.m, ret * 500, ret / (2 * a[i] / c[i])))
T = pd.DataFrame(rows, columns=["品种", "方向", "d", "自身200日线上", "自身50日线上", "宏观", "u", "r"]).dropna(subset=["宏观"])
T.to_csv("gold_macro_trades.csv", index=False)
era = lambda x: "2006-12" if x.year <= 2012 else "2013-19" if x.year <= 2019 else "2020-26"
T["段"] = T.d.map(era)


def s2(g):
    out = {"笔": len(g), "每次U": round(g.u.mean(), 1), "平均R": round(g.r.mean(), 2), "胜%": round((g.u > 0).mean() * 100)}
    for e in ("2006-12", "2013-19", "2020-26"):
        x = g[g.段 == e]; out[e] = round(x.r.mean(), 2) if len(x) >= 5 else np.nan
    return pd.Series(out)


print("\n== 二、日线突破（2006~2026，COMEX期货），按自身200日线 ==")
print(T.groupby(["品种", "方向", "自身200日线上"]).apply(s2).to_string())
print("\n按美元/利率（不看自身均线）"); print(T.groupby(["品种", "方向", "宏观"]).apply(s2).to_string())
print("\n自身200日线 × 美元/利率"); print(T.groupby(["品种", "方向", "自身200日线上", "宏观"]).apply(s2).to_string())
print("\n按自身50日线（更快的牛熊）"); print(T.groupby(["品种", "方向", "自身50日线上"]).apply(s2).to_string())
