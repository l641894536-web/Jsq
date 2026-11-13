"""A股选股策略组合回测（接 ashare_factor_bt.py 的结果）。
每月第一个交易日开盘按打分买前 N 只（等权），持有20个交易日；手续费+滑点按换掉的部分 0.25%（来回）扣。
打分（范围内百分位平均，越大越好）：
  牛市（全A等权在200日线上）：小市值、净利润增速在加快、离一年高点近、站上200日线
  熊市：小市值、跌得多（离一年高点远、在200日线下）、近一月没放量（换手放大低）
对照：范围内等权、最小市值 N 只、只用牛市打分、只用熊市打分；沪深300、中证1000（同样开盘买到第20天收盘）。
择时：一直持有 / 熊市不持有 / 熊市只在情绪温度<40时持有。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load

F = pd.read_pickle("/home/claude/bt/_factors.pkl"); z = np.load("/home/claude/bt/_factor_base.npz", allow_pickle=True)
R, fwd, U, bull, per = z["R"], z["fwd"], z["U"], z["bull"], z["per"]
rd = pd.to_datetime(z["rd"])
sent = pd.read_pickle("/home/claude/bt/_asent.pkl")
temp = sent["温度"].reindex(rd - pd.Timedelta(days=1), method="ffill").to_numpy()   # 换仓前一天收盘的温度
NS = [10, 30, 50]
COST = 0.0025


def prank(x, m):
    out = np.full(x.shape, np.nan)
    v = x[m]; ok = np.isfinite(v)
    r = pd.Series(v[ok]).rank(pct=True).to_numpy()
    tmp = np.full(v.shape, np.nan); tmp[ok] = r; out[m] = tmp
    return out


def score(k, mode):
    m = U[k]
    parts = {"小": -F["总市值"][k], "加速": F["净利润增速变化"][k], "近高": F["离一年高点"][k], "200上": F["站上200日线"][k],
             "跌多": -F["离一年高点"][k], "200下": -F["站上200日线"][k], "没放量": -F["换手放大(20日/一年)"][k]}
    use = {"牛": ["小", "加速", "近高", "200上"], "熊": ["小", "跌多", "200下", "没放量"], "小": ["小"]}[mode]
    S = np.nanmean(np.vstack([prank(parts[p], m) for p in use]), 0)
    S[~m] = np.nan
    return S


def run(mode, n, timing="always"):
    rets, prev = [], set()
    for k in range(len(R)):
        md = mode if mode in ("牛", "熊", "小") else ("牛" if bull[k] else "熊")
        hold = timing == "always" or (timing == "bullonly" and bull[k]) or (timing == "cold" and (bull[k] or temp[k] < 40))
        if not hold:
            rets.append(0.0); prev = set(); continue
        S = score(k, md); ok = np.isfinite(S) & np.isfinite(fwd[k])
        idx = np.where(ok)[0][np.argsort(-S[ok])[:n]]
        cur = set(idx.tolist()); turn = 1 - len(cur & prev) / n if prev else 1.0
        rets.append(np.nanmean(fwd[k, idx]) - COST * turn); prev = cur
    return np.array(rets)


ix = load.a_share_index(start="2015-06-01")
def idx_ret(code):
    g = ix[ix.code == code].set_index("date").sort_index()
    o, c = g.open.to_numpy(), g.close.to_numpy(); d = g.index
    out = []
    for t in rd:
        i = d.searchsorted(t)
        out.append(c[i + 19] / o[i] - 1 if i + 19 < len(c) else np.nan)
    return np.array(out)
ew = np.array([np.nanmean(fwd[k, U[k]]) for k in range(len(R))])
B = {"范围内等权": ew, "沪深300": idx_ret("sh.000300"), "中证1000": idx_ret("sh.000852")}


def stats(r, m):
    r = r[m]; r = r[np.isfinite(r)]
    eq = np.cumprod(1 + r); yrs = len(r) / 12
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    return eq[-1] ** (1 / yrs) - 1, dd, r.mean(), (r > 0).mean(), r.min()


rows = []
cands = {f"切换·前{n}": run("auto", n) for n in NS}
cands.update({f"切换·前30·熊市空仓": run("auto", 30, "bullonly"), f"切换·前30·熊市只在偏冷时拿": run("auto", 30, "cold"),
              "只用牛市打分·前30": run("牛", 30), "只用熊市打分·前30": run("熊", 30), "最小市值·前30": run("小", 30)})
cands.update(B)
W5 = per != "2016-21"
for name, r in cands.items():
    row = {"策略": name}
    for lab, m in [("近5年", W5), ("前半", per == "前半"), ("后半", per == "后半"), ("2016-21", per == "2016-21")]:
        a, dd, mu, wn, mn = stats(r, m)
        if lab == "近5年":
            row.update({"年化": a, "最大回撤": dd, "最差一月": mn, "赚钱月份": wn})
        else:
            row[lab + "年化"] = a
    row["跑赢等权的月"] = f"{int(((r - ew)[W5] > 0).sum())}/{int(W5.sum())}"
    rows.append(row)
O = pd.DataFrame(rows)
pd.set_option("display.width", 250)
fmt = O.copy()
for c in ["年化", "最大回撤", "最差一月", "赚钱月份", "前半年化", "后半年化", "2016-21年化"]:
    fmt[c] = fmt[c].map(lambda v: f"{v*100:+.1f}%")
print("== 月度换仓组合（扣 0.25% 来回成本）==")
print(fmt.to_string(index=False))
# 分年
yr = rd.year
Y = pd.DataFrame({k: pd.Series(v).groupby(yr).apply(lambda s: np.prod(1 + s.fillna(0)) - 1) for k, v in cands.items()
                  if k in ["切换·前30", "切换·前30·熊市只在偏冷时拿", "最小市值·前30", "范围内等权", "沪深300", "中证1000"]})
print("\n== 分年 ==")
print((Y * 100).round(1).to_string())
pd.to_pickle({"cands": cands, "rd": rd, "per": per, "bull": bull, "temp": temp}, "/home/claude/bt/_strategy.pkl")
