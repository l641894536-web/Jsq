"""两个弱点：①涨了怕卖飞（哪怕还亏着也不卖）②跌了当机会去加仓、结果被套。
A股（全市场，日均成交≥3000万、非ST）和美股（标普500+其他约600只）2021-11→2026-11，前后两段。
事件（每只股票触发后冷却20个交易日）：
  涨：10个交易日内涨了≥15%（收盘）；  跌：10个交易日内跌了≥15%
状态（事件当天能看到）：
  上升趋势：站在200日线上、离一年高点不到30%
  深跌中：离一年高点跌了30%以上
  其他：在200日线下但没深跌
另按"深跌后的反弹阶段"（口径同 research/bounce_bt.py）：第一波反弹（从低点涨回15%）、二次确认（回踩不破前低、再过反弹高点）。
结果：之后20/60/120天涨跌、比大盘（范围内等权）；之后60天里"又跌回事件前价格以下"（涨的事件：白涨了）/"再跌10%以上"（跌的事件：越套越深）的比例。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load
import apanel

START, MID = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-15")


def panel_a():
    P = apanel.build(extra=True)
    dates = pd.to_datetime(P["dates"]); traded = (np.nan_to_num(P["tradestatus"]) == 1) & np.isfinite(P["close"]) & (np.nan_to_num(P["amount"]) > 0)
    st = np.nan_to_num(P["isST"]).astype(bool); age = np.cumsum(traded, axis=0)
    pct = np.where(traded, P["pctChg"] / 100, np.nan)
    adj = np.where(traded, np.cumprod(1 + np.nan_to_num(pct), axis=0), np.nan)
    adjf = pd.DataFrame(adj).ffill().to_numpy()
    am20 = pd.DataFrame(np.where(traded, P["amount"], np.nan)).rolling(20, min_periods=10).mean().to_numpy()
    U = traded & ~st & (age >= 250) & (am20 >= 3e7)
    ew = pd.Series(np.nanmean(np.where(traded & ~st & (age >= 60), pct, np.nan), 1), index=dates).fillna(0)
    return dates, adjf, U, ew


def panel_us():
    uni = load.us_universe()
    tk = [t for t in uni.ticker if "=" not in t and "^" not in t and "-" not in t]
    d = load.us_daily(tk, start="2019-06-01")
    C = d.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    V = d.pivot(index="date", columns="ticker", values="volume").reindex_like(C)
    bad = set("BITO DRAM EIDO EWJ EWT EWY EWZ EWZS GDX INTW IWM KORU KSTR LYTE MSTU MUU MVLL NVDL QQQ RAM SKDD SKUU SMH SNXX SOXL SOXS SQQQ TBT TMF TQQQ TSLL TZA URNM XBI XLE SPY".split())
    C = C[[c for c in C.columns if c not in bad]]
    V = V[C.columns]
    dv = (C * V).rolling(20, min_periods=10).mean()
    U = (C.notna() & (dv >= 2e7)).to_numpy() & (C.notna().cumsum() >= 250).to_numpy()
    r = C.pct_change(fill_method=None).clip(-0.5, 0.5)
    ew = r.where(U).mean(axis=1).fillna(0)
    return C.index, C.ffill().to_numpy(), U, ew


def study(dates, adjf, U, ew, lab):
    T, N = adjf.shape
    A = pd.DataFrame(adjf)
    ma200 = A.rolling(200, min_periods=150).mean().to_numpy()
    hi250 = A.rolling(250, min_periods=200).max().to_numpy()
    mn120 = A.rolling(120, min_periods=100).min().to_numpy()
    ewi = (1 + ew).cumprod().to_numpy()
    r10 = adjf / np.vstack([np.full((10, N), np.nan), adjf[:-10]]) - 1
    t0 = dates.searchsorted(START)
    rows = []
    for kind, trig in [("涨", r10 >= 0.15), ("跌", r10 <= -0.15)]:
        trig = trig & U
        trig[:t0] = False; trig[T - 121:] = False
        for j in range(N):
            idx = np.where(trig[:, j])[0]
            last = -999
            for i in idx:
                if i - last < 20:
                    continue
                last = i
                c = adjf[i, j]
                dd = c / hi250[i, j] - 1
                above = c > ma200[i, j]
                state = "上升趋势" if (above and dd > -0.3) else ("深跌中" if dd <= -0.3 else "其他")
                f = {h: adjf[i + h, j] / c - 1 for h in (20, 60, 120)}
                fx = {h: f[h] - (ewi[i + h] / ewi[i] - 1) for h in (20, 60, 120)}
                path = adjf[i + 1:i + 61, j]
                pre = adjf[i - 10, j]
                if kind == "涨":
                    giveback = np.nanmin(path) < pre            # 60天内跌回涨之前
                    further = np.nanmax(path) > c * 1.15         # 60天内又涨15%（卖了就卖飞）
                else:
                    giveback = np.nanmin(path) < c * 0.9         # 60天内再跌10%（越套越深）
                    further = np.nanmax(path) > pre              # 60天内涨回跌之前（买对了）
                rows.append(dict(kind=kind, state=state, d=dates[i], f20=f[20], f60=f[60], f120=f[120], x60=fx[60], x120=fx[120],
                                 giveback=giveback, further=further, per="前半" if dates[i] < MID else "后半", above=above, dd=dd))
    R = pd.DataFrame(rows)
    pct = lambda v: f"{v*100:+.1f}%"
    print(f"\n######## {lab}：{len(R):,} 次事件")
    for kind in ["涨", "跌"]:
        print(f"\n== 10天{'涨' if kind=='涨' else '跌'}了15%以上之后 ==")
        out = []
        for stt in ["上升趋势", "其他", "深跌中"]:
            x = R[(R.kind == kind) & (R.state == stt)]
            if not len(x): continue
            out.append({"状态": stt, "次数": len(x), "之后20天": pct(x.f20.mean()), "60天": pct(x.f60.mean()), "120天": pct(x.f120.mean()),
                        "120天比大盘": pct(x.x120.mean()), "120天比大盘·前/后": f"{pct(x[x.per=='前半'].x120.mean())}/{pct(x[x.per=='后半'].x120.mean())}",
                        ("60天内跌回涨前" if kind == "涨" else "60天内再跌10%"): f"{x.giveback.mean():.0%}",
                        ("60天内再涨15%" if kind == "涨" else "60天内涨回跌前"): f"{x.further.mean():.0%}"})
        print(pd.DataFrame(out).to_string(index=False))
    return R


if __name__ == "__main__":
    RA = study(*panel_a(), "A股")
    RU = study(*panel_us(), "美股")
    pd.to_pickle({"A": RA, "US": RU}, "/home/claude/bt/_rally_dip.pkl")
