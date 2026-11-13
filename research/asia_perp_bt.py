"""亚洲股票合约（三星、SK海力士、腾讯）：本体收盘后合约的偏离、第二天开盘跟不跟、当晚美股的影响。
时间（UTC）：韩国 00:00 开盘 / 06:30 收盘；香港 01:30 开盘 / 08:00 收盘。合约价用整点K线的开盘价近似。
  dev   = 合约从本体收盘后到下一个本体开盘的涨跌（韩国 07:00→次日00:00；香港 08:00→次日01:00）
  gap   = 本体第二天开盘相对前一天收盘的跳空（按汇率换成美元）
  intra = 本体第二天开盘到收盘的涨跌
  us    = 当晚美股交易时段涨跌（纳指QQQ、半导体SMH、韩国ETF EWY：开盘→收盘）
看：合约收盘后走的那一段，第二天本体开盘是不是照着跳（合约领先）；开盘后是继续还是回吐；美股当晚涨跌和合约偏离的关系；
能不能变成能做的单子（扣 0.1% 手续费；样本只有 2026-06 起几个月，前后两半都要看）。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np, pandas as pd
from market_data import load

CFG = {"SAMSUNGUSDT": ("005930.KS", "KRW=X", 7, 0, "三星"), "SKHYNIXUSDT": ("000660.KS", "KRW=X", 7, 0, "SK海力士"),
       "TENCENTUSDT": ("0700.HK", "HKD=X", 8, 1, "腾讯")}
D = load.us_daily(["005930.KS", "000660.KS", "0700.HK", "KRW=X", "HKD=X", "QQQ", "SMH", "EWY"])
D["date"] = pd.to_datetime(D.date)
px = {t: g.set_index("date").sort_index() for t, g in D.groupby("ticker")}


def pat(H, ts):
    """ts 这个整点的价格（那根小时线的开盘价）"""
    i = H.index.searchsorted(ts)
    if i < len(H) and H.index[i] == ts: return H.open.iloc[i]
    return np.nan


rows = []
for perp, (tk, fx, close_h, open_h, nm) in CFG.items():
    H = load.binance("1h", perp).set_index("ts").sort_index()
    U = px[tk]; F = px[fx].close.reindex(U.index, method="ffill")
    days = U.index[(U.index >= H.index.min().tz_localize(None).normalize())]
    for a, b in zip(days[:-1], days[1:]):
        tc = pd.Timestamp(a).tz_localize("UTC") + pd.Timedelta(hours=close_h)          # 本体收盘后
        to = pd.Timestamp(b).tz_localize("UTC") + pd.Timedelta(hours=open_h)           # 下一个开盘
        tcb = pd.Timestamp(b).tz_localize("UTC") + pd.Timedelta(hours=close_h)         # 第二天收盘后
        p_c, p_o, p_cb = pat(H, tc), pat(H, to), pat(H, tcb)
        if not (np.isfinite(p_c) and np.isfinite(p_o) and np.isfinite(p_cb)): continue
        uc_a, uo_b, uc_b = U.close.loc[a] / F.loc[a], U.open.loc[b] / F.loc[b], U.close.loc[b] / F.loc[b]
        us = {}
        for t in ("QQQ", "SMH", "EWY"):
            P = px[t]
            if a in P.index: us[t] = P.close.loc[a] / P.open.loc[a] - 1                  # 当晚（同一天美国时间）交易时段
            else: us[t] = np.nan
        rows.append(dict(sym=nm, d=a, basis=p_c / uc_a - 1, dev=p_o / p_c - 1, gap=uo_b / uc_a - 1, intra=uc_b / uo_b - 1,
                         perp_day=p_cb / p_o - 1, **{f"us_{k}": v for k, v in us.items()}))
T = pd.DataFrame(rows).dropna()
pd.set_option("display.width", 220)
print(f"样本：{T.d.min().date()} → {T.d.max().date()}，", T.groupby("sym").size().to_dict())
for nm, x in T.groupby("sym"):
    c = np.polyfit(x.dev, x.gap, 1)
    print(f"\n== {nm}（{len(x)} 天）")
    print(f"收盘时合约比本体贵 {x.basis.median()*100:+.2f}%（中位），收盘后到下个开盘合约平均走 {x.dev.abs().mean()*100:.2f}%（绝对值），最大 {x.dev.abs().max()*100:.1f}%")
    print(f"第二天本体开盘跳空 ≈ {c[0]:.2f} × 合约收盘后的涨跌 {c[1]*100:+.2f}%；相关 {np.corrcoef(x.dev, x.gap)[0,1]:.2f}（1 = 完全照着跳）")
    print(f"开盘后到收盘：和合约收盘后涨跌的相关 {np.corrcoef(x.dev, x.intra)[0,1]:+.2f}（负 = 回吐，正 = 继续）")
    for t in ("QQQ", "SMH", "EWY"):
        print(f"  当晚 {t} 交易时段涨跌 vs 合约收盘后涨跌 相关 {np.corrcoef(x[f'us_{t}'], x.dev)[0,1]:+.2f}；vs 第二天本体开盘后 相关 {np.corrcoef(x[f'us_{t}'], x.intra)[0,1]:+.2f}")
    # 可做的单子：合约收盘后涨/跌超过阈值 → 第二天开盘反着做（赌回吐），拿到收盘；或顺着做
    mid = x.d.quantile(0.5)
    for thr in (0.01, 0.02, 0.03):
        big = x[x.dev.abs() >= thr]
        if len(big) < 5: continue
        rev = -np.sign(big.dev) * big.perp_day - 0.001
        print(f"  收盘后合约走了 ≥{thr*100:.0f}% 的 {len(big)} 天：第二天开盘反着做到收盘 每次 {rev.mean()*100:+.2f}%（赚的 {(rev>0).mean()*100:.0f}%；"
              f"前半 {rev[big.d < mid].mean()*100:+.2f}% / 后半 {rev[big.d >= mid].mean()*100:+.2f}%）；100U开5倍约 {rev.mean()*500:+.1f}U")
# 美股当晚 → 合约在美股收盘后到亚洲开盘这段（21:00→次日开盘）有没有跟上（是不是慢半拍）
print("\n== 美股收盘后合约还会不会补涨补跌（美股当晚半导体 SMH 涨跌 → 合约 21:00 到下一个亚洲开盘）")
for perp, (tk, fx, close_h, open_h, nm) in CFG.items():
    H = load.binance("1h", perp).set_index("ts").sort_index(); x = T[T.sym == nm].copy()
    lag = []
    for r in x.itertuples():
        t21 = pd.Timestamp(r.d).tz_localize("UTC") + pd.Timedelta(hours=21); t_o = pd.Timestamp(r.d).tz_localize("UTC") + pd.Timedelta(days=1, hours=open_h)
        if r.d.weekday() == 4: t_o += pd.Timedelta(days=2)
        a, b = pat(H, t21), pat(H, t_o)
        lag.append(b / a - 1 if np.isfinite(a) and np.isfinite(b) else np.nan)
    x["lag"] = lag; x = x.dropna(subset=["lag"])
    sig = np.sign(x.us_SMH); ret = sig * x.lag - 0.001
    print(f"{nm}：{len(x)} 天，SMH 当晚涨跌 vs 合约之后几小时 相关 {np.corrcoef(x.us_SMH, x.lag)[0,1]:+.2f}；顺着美股方向做 每次 {ret.mean()*100:+.2f}%（赚的 {(ret>0).mean()*100:.0f}%）")
T.to_csv("/home/claude/bt/asia_perp_days.csv", index=False)
