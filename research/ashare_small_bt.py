"""小市值组合的稳健性：（接 ashare_factor_bt.py）
市值：2020-05 以后用总市值（最近一期财报总股本×收盘），之前用 成交额/换手率 估算的流通市值。
变体：只数 N、成交额门槛、成本、两段式（先取最小20%，再按牛熊打分）、风格择时。
"""
import numpy as np, pandas as pd
F = pd.read_pickle("/home/claude/bt/_factors.pkl"); z = np.load("/home/claude/bt/_factor_base.npz", allow_pickle=True)
R, fwd, U0, bull, per = z["R"], z["fwd"], z["U"], z["bull"], z["per"]
rd = pd.to_datetime(z["rd"]); yr = rd.year
temp = pd.read_pickle("/home/claude/bt/_strategy.pkl")["temp"]
B = pd.read_pickle("/home/claude/bt/_strategy.pkl")["cands"]
size = np.where(np.isfinite(F["总市值"]), F["总市值"], F["流通市值"])
amt20 = F["20日成交额"]
ew = np.array([np.nanmean(fwd[k, U0[k]]) for k in range(len(R))])


def prank(x, m):
    out = np.full(x.shape, np.nan); v = x[m]; ok = np.isfinite(v)
    tmp = np.full(v.shape, np.nan); tmp[ok] = pd.Series(v[ok]).rank(pct=True).to_numpy(); out[m] = tmp
    return out


def basket(k, n, minamt=3e7, two=False):
    m = U0[k] & (amt20[k] >= minamt) & np.isfinite(size[k]) & np.isfinite(fwd[k])
    if two:
        cut = np.nanquantile(size[k][m], 0.2); m2 = m & (size[k] <= cut)
        if bull[k]:
            parts = [F["净利润增速变化"][k], F["离一年高点"][k], F["站上200日线"][k]]
        else:
            parts = [-F["离一年高点"][k], -F["站上200日线"][k], -F["换手放大(20日/一年)"][k]]
        S = np.nanmean(np.vstack([prank(p, m2) for p in parts]), 0); S[~m2] = np.nan
        ok = np.isfinite(S); return np.where(ok)[0][np.argsort(-S[ok])[:n]]
    ok = np.where(m)[0]; return ok[np.argsort(size[k][ok])[:n]]


def run(n=30, minamt=3e7, cost=0.0025, two=False, timing=None):
    rets, prev, raw = [], set(), []
    for k in range(len(R)):
        idx = basket(k, n, minamt, two)
        r_b = np.nanmean(fwd[k, idx]); raw.append(r_b)
        cur = set(idx.tolist()); turn = 1 - len(cur & prev) / n if prev else 1.0
        hold = True
        if timing == "style" and k >= 3:          # 过去3个月小市值组合跑输等权就换成等权
            hold = np.nansum(np.array(raw[k - 3:k]) - ew[k - 3:k]) > 0
        if timing == "hot":                       # 情绪过热（温度>80）这个月不拿
            hold = temp[k] <= 80
        if timing == "style":
            rets.append((r_b - cost * turn) if hold else ew[k] - cost); prev = cur if hold else set()
        else:
            rets.append((r_b - cost * turn) if hold else 0.0); prev = cur if hold else set()
    return np.array(rets)


def st(r, m):
    r = r[m]; eq = np.cumprod(1 + r); yrs = len(r) / 12
    return eq[-1] ** (1 / yrs) - 1, (eq / np.maximum.accumulate(eq) - 1).min(), r.min()


W5 = per != "2016-21"
V = {}
for n in (10, 30, 50, 100):
    V[f"最小{n}只"] = run(n)
for a in (1e7, 5e7, 1e8):
    V[f"最小30只·成交≥{a/1e7:.0f}千万"] = run(30, a)
V["最小30只·成本0.5%"] = run(30, cost=0.005)
V["两段式·最小20%里按牛熊打分前30"] = run(30, two=True)
V["最小30只·风格择时"] = run(30, timing="style")
V["最小30只·过热不拿"] = run(30, timing="hot")
V["范围内等权"] = ew; V["沪深300"] = B["沪深300"]; V["中证1000"] = B["中证1000"]
rows = []
for k, r in V.items():
    a5, dd5, mn5 = st(r, W5); a1, _, _ = st(r, per == "前半"); a2, _, _ = st(r, per == "后半"); a0, dd0, _ = st(r, per == "2016-21")
    rows.append({"组合": k, "近5年年化": a5, "最大回撤": dd5, "最差一月": mn5, "前半": a1, "后半": a2, "2016-21年化": a0, "2016-21回撤": dd0,
                 "跑赢等权月": f"{int(((r - ew)[W5] > 0).sum())}/{int(W5.sum())}"})
O = pd.DataFrame(rows)
for c in O.columns[1:-1]:
    O[c] = O[c].map(lambda v: f"{v*100:+.1f}%")
pd.set_option("display.width", 250)
print(O.to_string(index=False))
Y = pd.DataFrame({k: pd.Series(V[k]).groupby(yr).apply(lambda s: np.prod(1 + s) - 1) for k in ["最小30只", "两段式·最小20%里按牛熊打分前30", "最小30只·风格择时", "范围内等权", "沪深300", "中证1000"]})
print("\n分年（%）"); print((Y * 100).round(1).to_string())
r = V["最小30只"]; worst = np.argsort(r)[:6]
print("\n最差的6个月：", [(str(rd[i].date()), round(r[i] * 100, 1), round(ew[i] * 100, 1)) for i in worst])
pd.to_pickle({"V": V, "rd": rd, "per": per}, "/home/claude/bt/_small.pkl")
# 现在的名单（最近一次换仓）
k = len(R) - 1
print("\n最近一次换仓", rd[k].date(), "最小30只的市值上限（亿）", round(float(np.sort(size[k][U0[k] & np.isfinite(size[k])])[29]), 1))
