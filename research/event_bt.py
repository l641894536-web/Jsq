"""美国大数据日：CPI（8:30 ET）、非农（8:30 ET）、美联储议息（14:00 ET 声明）。
看黄金/白银（Dukascopy 1h）、比特币（币安 1h）、QQQ/AMD（Yahoo 1h，只有近2年、只有正规交易时段）在公布那一小时：
  1) 波动是平时同一时段的几倍
  2) 公布后4小时内，前24小时的高点/低点被扫到的概率（用户的止损习惯：多单放24小时低点下方）
  3) 第一小时的方向之后24小时是延续还是回吐
  4) 交易台现行规则的单子：在公布前后进场的 / 拿着单子过公布的，和其他单子比
日期来自 federalreserve.gov FOMC 日历、bls.gov CPI 和 Employment Situation 发布存档。
"""
import os, sys
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
sys.path.insert(0, "/home/claude/jsq"); os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
from market_data import load

CPI = """2021-01-13 2021-02-10 2021-03-10 2021-04-13 2021-05-12 2021-06-10 2021-07-13 2021-08-11 2021-09-14 2021-10-13 2021-11-10 2021-12-10
2022-01-12 2022-02-10 2022-03-10 2022-04-12 2022-05-11 2022-06-10 2022-07-13 2022-08-10 2022-09-13 2022-10-13 2022-11-10 2022-12-13
2023-01-12 2023-02-14 2023-03-14 2023-04-12 2023-05-10 2023-06-13 2023-07-12 2023-08-10 2023-09-13 2023-10-12 2023-11-14 2023-12-12
2024-01-11 2024-02-13 2024-03-12 2024-04-10 2024-05-15 2024-06-12 2024-07-11 2024-08-14 2024-09-11 2024-10-10 2024-11-13 2024-12-11
2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15 2025-08-12 2025-09-11 2025-10-24 2025-12-18
2026-01-13 2026-02-13 2026-03-11 2026-04-10 2026-05-12 2026-06-10 2026-07-14 2026-08-12 2026-09-11 2026-10-14 2026-11-10""".split()
NFP = """2021-02-05 2021-03-05 2021-04-02 2021-05-07 2021-06-04 2021-07-02 2021-08-06 2021-09-03 2021-10-08 2021-11-05 2021-12-03
2022-01-07 2022-02-04 2022-03-04 2022-04-01 2022-05-06 2022-06-03 2022-07-08 2022-08-05 2022-09-02 2022-10-07 2022-11-04 2022-12-02
2023-01-06 2023-02-03 2023-03-10 2023-04-07 2023-05-05 2023-06-02 2023-07-07 2023-08-04 2023-09-01 2023-10-06 2023-11-03 2023-12-08
2024-01-05 2024-02-02 2024-03-08 2024-04-05 2024-05-03 2024-06-07 2024-07-05 2024-08-02 2024-09-06 2024-10-04 2024-11-01 2024-12-06
2025-01-10 2025-02-07 2025-03-07 2025-04-04 2025-05-02 2025-06-06 2025-07-03 2025-08-01 2025-09-05 2025-11-20 2025-12-16
2026-01-09 2026-02-11 2026-03-06 2026-04-03 2026-05-08 2026-06-05 2026-07-02 2026-08-07 2026-09-04 2026-10-02 2026-11-06""".split()
FOMC = """2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16 2026-10-28""".split()
NY = ZoneInfo("America/New_York")


def utc(d, hm):
    h, m = hm
    return pd.Timestamp(f"{d} {h:02d}:{m:02d}", tz=NY).tz_convert("UTC")


EV = pd.DataFrame([(k, utc(d, hm)) for k, L, hm in [("CPI", CPI, (8, 30)), ("非农", NFP, (8, 30)), ("议息", FOMC, (14, 0))] for d in L],
                  columns=["kind", "t"])
EV = EV[EV.t >= "2021-11-01"].sort_values("t").reset_index(drop=True)
EV.to_csv("/home/claude/bt/_events.csv", index=False)
print("事件数：", EV.kind.value_counts().to_dict())

# ---------------- 行情（小时线，ts = 这根K线开始的时间）
S = {}
d = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-09-01")
for s_, g in d.groupby("symbol"):
    S[{"XAUUSD": "黄金", "XAGUSD": "白银"}[s_]] = g.set_index("ts")[["open", "high", "low", "close"]].astype(float).sort_index()
b = load.binance("1h", ["BTCUSDT"], start="2021-09-01")
tc = [c for c in b.columns if c in ("ts", "open_time", "time", "date")][0]
b[tc] = pd.to_datetime(b[tc], utc=True)
S["比特币"] = b.set_index(tc)[["open", "high", "low", "close"]].astype(float).sort_index()
u = load.us_hourly(["QQQ", "AMD"])
for s_, g in u.groupby("ticker"):
    S[{"QQQ": "纳指QQQ", "AMD": "AMD"}[s_]] = g.set_index("ts")[["open", "high", "low", "close"]].astype(float).sort_index()


def study(name, px, ev):
    """ev: 事件时间（UTC）。股票只有正规时段：8:30 的数据看开盘那根（9:30），14:00 看包含它的那根。"""
    idx = px.index; hod = idx.hour + idx.minute / 60
    rng = ((px.high - px.low) / px.close.shift(1)).to_numpy()
    H, L, C = px.high.to_numpy(), px.low.to_numpy(), px.close.to_numpy()
    rows = []
    evset = set()
    for _, e in ev.iterrows():
        k = idx.searchsorted(e.t, side="right") - 1          # 包含公布时刻的那根（股票：公布在开盘前就取开盘那根）
        if k < 0 or idx[k] + pd.Timedelta(hours=1) <= e.t:
            k = idx.searchsorted(e.t)
        if k < 30 or k + 24 >= len(idx) or (idx[k] - e.t) > pd.Timedelta(hours=2):
            continue
        evset.add(idx[k].normalize())
        rows.append((e.kind, k))
    out = []
    for kind, k in rows:
        same = np.where((np.abs(hod - hod[k]) < 0.01) & (idx < idx[k]) & (idx >= idx[k] - pd.Timedelta(days=90)))[0]
        same = [j for j in same if idx[j].normalize() not in evset][-60:]
        if len(same) < 15:
            continue
        base = np.nanmedian(rng[same])
        h24, l24 = H[k - 24:k].max(), L[k - 24:k].min()
        swept = lambda j: (L[j:j + 4].min() < l24, H[j:j + 4].max() > h24)
        sl, sh = swept(k)
        nl = np.mean([swept(j)[0] if j >= 24 else np.nan for j in same])
        nh = np.mean([swept(j)[1] if j >= 24 else np.nan for j in same])
        # 24小时扫止损时要按各自的24h区间算
        nl = np.nanmean([L[j:j + 4].min() < L[j - 24:j].min() for j in same if j >= 24])
        nh = np.nanmean([H[j:j + 4].max() > H[j - 24:j].max() for j in same if j >= 24])
        r1 = C[k] / C[k - 1] - 1; r24 = C[k + 24] / C[k] - 1; r4 = C[k + 3] / C[k - 1] - 1
        out.append(dict(品种=name, 事件=kind, t=idx[k], 倍数=rng[k] / base, 扫低=sl, 扫高=sh, 平时扫低=nl, 平时扫高=nh,
                        r1=r1, r24=r24, r4=r4, 同向=np.sign(r1) == np.sign(r24)))
    return pd.DataFrame(out)


R = pd.concat([study(n, p, EV) for n, p in S.items()], ignore_index=True)
R.to_pickle("/home/claude/bt/_event_R.pkl")
mid = pd.Timestamp("2024-05-15", tz="UTC")
pd.set_option("display.width", 220)
print("\n== 公布那一小时的波动（平时同一时段的几倍，中位数）/ 公布后4小时扫掉前24小时低点、高点的概率 ==")
g = R.groupby(["品种", "事件"])
T = pd.DataFrame({"次数": g.size(), "波动倍数": g.倍数.median().round(1), "前半": R[R.t < mid].groupby(["品种", "事件"]).倍数.median().round(1),
                  "后半": R[R.t >= mid].groupby(["品种", "事件"]).倍数.median().round(1),
                  "扫低": (g.扫低.mean() * 100).round(0), "平时扫低": (g.平时扫低.mean() * 100).round(0),
                  "扫高": (g.扫高.mean() * 100).round(0), "平时扫高": (g.平时扫高.mean() * 100).round(0),
                  "第一小时方向24h后还对": (g.同向.mean() * 100).round(0)})
print(T.to_string())
print("\n== 第一小时之后24小时：顺着第一小时方向的平均涨跌（正=延续，负=回吐），单位%；以及第一小时平均绝对涨跌 ==")
R["顺向24h"] = np.sign(R.r1) * R.r24
T2 = R.groupby(["品种", "事件"]).agg(第一小时绝对=("r1", lambda v: v.abs().mean() * 100), 顺向24h=("顺向24h", lambda v: v.mean() * 100)).round(2)
T2["前半"] = (R[R.t < mid].groupby(["品种", "事件"]).顺向24h.mean() * 100).round(2)
T2["后半"] = (R[R.t >= mid].groupby(["品种", "事件"]).顺向24h.mean() * 100).round(2)
print(T2.to_string())

# ---------------- 交易台规则的单子
A = pd.read_csv("/home/claude/bt/risk_trades.csv.gz", parse_dates=["ts", "exit_ts"])
A["ts"] = pd.to_datetime(A.ts, utc=True); A["exit_ts"] = pd.to_datetime(A.exit_ts, utc=True)
evt = pd.DatetimeIndex(EV.t.sort_values()).tz_convert("UTC").tz_localize(None).to_numpy()
def near(ts, before, after):
    t0 = ts.tz_convert("UTC").tz_localize(None).to_datetime64(); i = np.searchsorted(evt, t0)
    c = [evt[j] for j in (i - 1, i) if 0 <= j < len(evt)]
    return any(x - np.timedelta64(before, "h") <= t0 <= x + np.timedelta64(after, "h") for x in c)
A["进场在公布前后"] = A.ts.map(lambda x: near(x, 2, 2))
A["拿着过公布"] = [bool(((evt > a.ts.tz_convert("UTC").tz_localize(None).to_datetime64()) & (evt < a.exit_ts.tz_convert("UTC").tz_localize(None).to_datetime64())).any()) if pd.notna(a.exit_ts) else False for a in A.itertuples()]
A["期"] = np.where(A.ts < mid, "前半", "后半")
print("\n== 交易台规则的单子（100U开5倍每次赚亏U）==")
for col in ["进场在公布前后", "拿着过公布"]:
    t = A.groupby(["G", col]).u.agg(["size", "mean"]).round(2)
    t2 = A.groupby(["G", col, "期"]).u.mean().unstack().round(2)
    print(f"-- {col}（公布前2小时到后2小时内进场）" if col == "进场在公布前后" else f"-- {col}")
    print(t.join(t2).to_string())
A.to_pickle("/home/claude/bt/_event_trades.pkl")
