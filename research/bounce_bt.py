"""深跌之后的上涨：是反弹还是反转？（正股，美股 + A股，2020 起）
事件 E1"反弹出现"：股票比一年高点跌了 >=30%，从近120天最低收盘价 L 涨回 15%（第一次达到，低点在40个交易日内）。
事件 E2"二次确认"：E1 之后回踩（从反弹高点回落 >=8%）但没破 L，随后收盘价超过前一个反弹高点。
结果：之后120个交易日内有没有跌破 L（=只是反弹）；之后 60/120 天涨幅及相对大盘的超额。
特征（事件当天能看到的）：大盘在不在200日线上、股价是否站上50日线、50日线是否拐头向上、是否站上200日线、
  反弹快慢、放量、跌得多深、大盘是否同时在反弹。
用法: python3 bounce_bt.py us|a
"""
import sys
import numpy as np, pandas as pd

mk = sys.argv[1]
C = pd.read_pickle(f"/tmp/{mk}_c.pkl").sort_index(); V = pd.read_pickle(f"/tmp/{mk}_v.pkl").sort_index().reindex_like(C)
if mk == "us":
    bad = set("BITO DRAM EIDO EWJ EWT EWY EWZ EWZS GDX INTW IWM KORU KSTR LYTE MSTU MUU MVLL NVDL QQQ RAM SKDD SKUU SMH SNXX SOXL SOXS SQQQ TBT TMF TQQQ TSLL TZA URNM XBI XLE SPY".split())
    mkt = C["QQQ"].ffill()
    C = C[[c for c in C.columns if c not in bad and "=" not in c and "^" not in c and "-" not in c]]
else:
    C = C[[c for c in C.columns if c[:6] in ("sh.600", "sh.601", "sh.603", "sh.605", "sh.688", "sz.000", "sz.001", "sz.002", "sz.003", "sz.300", "sz.301")]]
    mkt = (1 + C.pct_change(fill_method=None).clip(-0.21, 0.21).mean(axis=1).fillna(0)).cumprod()
V = V[C.columns]
days = C.index; n = len(days)
mbull = (mkt > mkt.rolling(200).mean()).values
mlow60 = mkt.rolling(60).min(); mbounce = ((mkt / mlow60 - 1 >= 0.05) & (mkt.rolling(60).apply(np.argmin, raw=True) >= 20)).values
mk_arr = mkt.values
START = np.searchsorted(days, pd.Timestamp("2020-06-01")); H = 120

rows = []
for s in C.columns:
    c = C[s].values.astype(float); v = V[s].values.astype(float)
    ok = ~np.isnan(c)
    if ok.sum() < 400: continue
    cs = pd.Series(c)
    mx250 = cs.rolling(250, min_periods=200).max().values
    mn120 = cs.rolling(120, min_periods=100).min().values
    am = cs.rolling(120, min_periods=100).apply(np.nanargmin, raw=True).values     # index within window
    ma50 = cs.rolling(50).mean().values; ma200 = cs.rolling(200).mean().values
    lastL = None
    i = max(START, 260)
    while i < n - 1:
        L = mn120[i]
        if not (c[i] == c[i] and L == L and mx250[i] == mx250[i]): i += 1; continue
        since = 119 - int(am[i]) if am[i] == am[i] else 999
        if c[i] >= L * 1.15 and since <= 40 and L <= 0.7 * mx250[i] and L != lastL and not (c[i - 1] >= L * 1.15):
            lastL = L; li = i - since

            def outcome(t):
                e = min(n - 1, t + H)
                if t + 60 >= n: return None
                seg = c[t + 1:e + 1]
                newlow = bool(np.nanmin(seg) < L) if len(seg) else False
                r60 = c[t + 60] / c[t] - 1; m60 = mk_arr[t + 60] / mk_arr[t] - 1
                r120 = c[e] / c[t] - 1 if t + H < n else np.nan
                m120 = mk_arr[e] / mk_arr[t] - 1 if t + H < n else np.nan
                mx = np.nanmax(seg) / c[t] - 1
                return newlow, r60, r60 - m60, r120, r120 - m120, mx

            def feats(t):
                v0 = np.nanmean(v[max(0, li - 50):li]) if li > 5 else np.nan
                v1 = np.nanmean(v[li:t + 1])
                return dict(mbull=bool(mbull[t]), ma50=bool(c[t] > ma50[t]), ma50up=bool(ma50[t] > ma50[t - 10]),
                            ma200=bool(c[t] > ma200[t]) if ma200[t] == ma200[t] else False, fast=since <= 10,
                            vol=bool(v1 >= 1.5 * v0) if v0 == v0 and v0 > 0 else False,
                            deep=bool(L <= 0.5 * mx250[i]), mbounce=bool(mbounce[t]))
            o = outcome(i)
            if o:
                rows.append(dict(ev="E1", s=s, d=days[i], **feats(i), newlow=o[0], r60=o[1], x60=o[2], r120=o[3], x120=o[4], mx=o[5]))
            # E2: 回踩不破再过前高
            P = c[i]; pulled = False; t = i + 1
            while t < min(n - 1, i + 120):
                if c[t] != c[t]: t += 1; continue
                if c[t] < L: break
                if not pulled:
                    if c[t] > P: P = c[t]
                    elif c[t] <= P * 0.92: pulled = True
                elif c[t] > P:
                    o2 = outcome(t)
                    if o2:
                        rows.append(dict(ev="E2", s=s, d=days[t], **feats(t), newlow=o2[0], r60=o2[1], x60=o2[2], r120=o2[3], x120=o2[4], mx=o2[5]))
                    break
                t += 1
        i += 1

t = pd.DataFrame(rows); t.to_csv(f"bounce_events_{mk}.csv.gz", index=False)
t["half"] = np.where(t.d < pd.Timestamp("2023-09-01"), 1, 2)
pd.set_option("display.width", 250)


def summ(g):
    return pd.Series({"n": len(g), "破前低%": round(g.newlow.mean() * 100), "60天%": round(g.r60.mean() * 100, 1),
                      "60天超额%": round(g.x60.mean() * 100, 1), "120天超额%": round(g.x120.mean() * 100, 1),
                      "超额h1": round(g[g.half == 1].x60.mean() * 100, 1), "超额h2": round(g[g.half == 2].x60.mean() * 100, 1),
                      "破低h1": round(g[g.half == 1].newlow.mean() * 100), "破低h2": round(g[g.half == 2].newlow.mean() * 100)})


print(mk, "事件数", t.groupby("ev").size().to_dict(), t.d.min().date(), t.d.max().date())
print(t.groupby("ev").apply(summ).to_string())
for f in ["mbull", "ma50up", "ma200", "ma50", "fast", "vol", "deep", "mbounce"]:
    print(f"\n-- {f}"); print(t.groupby(["ev", f]).apply(summ).to_string())
print("\n-- 组合：大盘牛熊 × 50日线拐头"); print(t.groupby(["ev", "mbull", "ma50up"]).apply(summ).to_string())
print("\n-- 组合：大盘牛熊 × 站上200日线"); print(t.groupby(["ev", "mbull", "ma200"]).apply(summ).to_string())
