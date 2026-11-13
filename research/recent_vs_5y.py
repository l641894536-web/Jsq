"""用最近一年当参照，会不会比用5年更好？

A 现行规则每一组：最近12个月 vs 之前4年
B 滚动检验（真正回答"要不要按最近一年来"）：每个月开头只看过去12个月（或6个月）这条规则赚没赚，赚了这个月才做；
  用的都是当时已经知道的数据，2022-11 到 2026-10 一个月一个月往前滚，和"一直照做"比
C 用户的想法：AMD/美光/戴尔 突破的那个价位反过来做空（突破失败），对称止损止盈，最多拿3天；5年 vs 最近一年；
  再滚动选"做多突破 还是 反着做空"，看按最近一年来选有没有用
成绩都是 100U 开5倍每笔赚亏 U（扣手续费）。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np, pandas as pd
from market_data import load

A = pd.read_csv("/home/claude/bt/risk_trades.csv.gz", parse_dates=["ts", "exit_ts"])
A["m"] = A.ts.dt.tz_convert(None).dt.to_period("M")
A["k"] = A.G + "·" + A.rule
CUT = pd.Timestamp("2025-11-01", tz="UTC")


def s(x):
    return pd.Series({"笔数": len(x), "每笔U": round(x.u.mean(), 2) if len(x) else np.nan, "合计U": round(x.u.sum()), "赚的比例": f"{(x.u > 0).mean() * 100:.0f}%" if len(x) else ""})


print("===== A 最近12个月（2025-11 到 2026-10）和之前4年比")
rows = []
for k, x in A.groupby("k"):
    a, b = x[x.ts < CUT], x[x.ts >= CUT]
    rows.append(dict(规则=k, 之前4年笔数=len(a), 之前每笔U=round(a.u.mean(), 2), 最近1年笔数=len(b), 最近1年每笔U=round(b.u.mean(), 2),
                     最近半年每笔U=round(x[x.ts >= pd.Timestamp("2026-05-01", tz="UTC")].u.mean(), 2)))
a, b = A[A.ts < CUT], A[A.ts >= CUT]
rows.append(dict(规则="全部", 之前4年笔数=len(a), 之前每笔U=round(a.u.mean(), 2), 最近1年笔数=len(b), 最近1年每笔U=round(b.u.mean(), 2),
                 最近半年每笔U=round(A[A.ts >= pd.Timestamp("2026-05-01", tz="UTC")].u.mean(), 2)))
print(pd.DataFrame(rows).to_string(index=False))


def walk(T, key, look, start="2022-11", end="2026-10", thr=0.0):
    """每个月只做 过去 look 个月 合计U>thr 的那几组；返回逐月 (一直做, 过滤后)"""
    M = T.groupby(["k", "m"]).u.sum().unstack(0).fillna(0)
    idx = pd.period_range(T.m.min(), end, freq="M"); M = M.reindex(idx, fill_value=0)
    out = []
    for m in pd.period_range(start, end, freq="M"):
        past = M.loc[m - look:m - 1].sum()
        on = past[past > thr].index
        out.append(dict(m=m, 一直做=M.loc[m].sum(), 按最近=M.loc[m, on].sum() if len(on) else 0.0, 开着几组=len(on)))
    return pd.DataFrame(out)


def dd(series):
    c = series.cumsum(); return round((c - c.cummax()).min())


print("\n===== B 滚动检验：每个月只做过去N个月赚钱的那几组（只用当时知道的数据）")
for look in (12, 6, 3):
    W = walk(A, "k", look)
    W["y"] = W.m.dt.year
    print(f"-- 看过去 {look} 个月：一直照做合计 {W.一直做.sum():.0f}U（最大回撤 {dd(W.一直做)}U）；按最近来 {W.按最近.sum():.0f}U（最大回撤 {dd(W.按最近)}U）")
    print("   每年：", W.groupby("y")[["一直做", "按最近"]].sum().round(0).astype(int).to_dict("index"))

# ---------------- C 股票突破反着做空
st = load.dukascopy([x + "USUSD" for x in ["AMD", "MU", "DELL"]], start="2021-06")
px = {}
for sym, g in st.groupby("symbol"):
    g = g.sort_values("ts").reset_index(drop=True); ny = g.ts.dt.tz_convert("America/New_York")
    g = g[(ny.dt.weekday < 5) & (ny.dt.hour >= 9) & (ny.dt.hour <= 15)].reset_index(drop=True)
    px[sym.replace("USUSD", "")] = g
B = A[(A.G == "股票") & (A.rule == "突破")].copy()
res = []
for r in B.itertuples():
    g = px.get(r.sym.replace("USDT", "")) if isinstance(r.sym, str) else None
    if g is None: continue
    i = g.ts.searchsorted(r.ts)
    if i >= len(g) or abs((g.ts.iloc[i] - r.ts).total_seconds()) > 3600: continue
    E = g.close.iloc[i]; Rk = r.R_pct * E
    for tgt in (1.0, 1.5):
        st_, tp, px_out = E + Rk, E - tgt * Rk, None
        for j in range(i + 1, min(len(g), i + 22)):
            if g.high.iloc[j] >= st_: px_out = max(st_, g.open.iloc[j]); break
            if g.low.iloc[j] <= tp: px_out = min(tp, g.open.iloc[j]); break
        if px_out is None: px_out = g.close.iloc[min(len(g) - 1, i + 21)]
        res.append(dict(ts=r.ts, sym=r.sym, tgt=tgt, u_long=r.u, u_fade=500 * ((E - px_out) / E - 0.001)))
F = pd.DataFrame(res)
print("\n===== C AMD/美光/戴尔 牛市突破：照做多 vs 在同一个价反着做空（止损=做多止损的距离，止盈=1倍/1.5倍，最多3天）")
for tgt, x in F.groupby("tgt"):
    a, b = x[x.ts < CUT], x[x.ts >= CUT]
    print(f"止盈{tgt}倍：5年 {len(x)} 笔，做多每笔 {x.u_long.mean():+.2f}U / 反着做空每笔 {x.u_fade.mean():+.2f}U（赚的比例 {(x.u_fade>0).mean()*100:.0f}%）；"
          f"之前4年 做多 {a.u_long.mean():+.2f} / 做空 {a.u_fade.mean():+.2f}；最近1年 {len(b)} 笔 做多 {b.u_long.mean():+.2f} / 做空 {b.u_fade.mean():+.2f}")
    x = x.copy(); x["y"] = x.ts.dt.year
    print("   每年 做多/做空：", {y: (round(v.u_long.mean(), 1), round(v.u_fade.mean(), 1), len(v)) for y, v in x.groupby("y")})
# 滚动选：过去12个月 做多合计 > 反着做空合计 就做多，否则反着做空
x = F[F.tgt == 1.0].copy(); x["m"] = x.ts.dt.tz_convert(None).dt.to_period("M")
ML = x.groupby("m").u_long.sum(); MF = x.groupby("m").u_fade.sum()
idx = pd.period_range(x.m.min(), "2026-10", freq="M"); ML = ML.reindex(idx, fill_value=0); MF = MF.reindex(idx, fill_value=0)
pick, al, af = 0.0, 0.0, 0.0
for m in pd.period_range("2022-11", "2026-10", freq="M"):
    useL = ML.loc[m - 12:m - 1].sum() >= MF.loc[m - 12:m - 1].sum()
    pick += ML.loc[m] if useL else MF.loc[m]; al += ML.loc[m]; af += MF.loc[m]
print(f"滚动选（看过去12个月哪个好就做哪个）：合计 {pick:.0f}U；一直做多 {al:.0f}U；一直反着做空 {af:.0f}U")
