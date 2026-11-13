"""信号出来以后晚进还值不值：AMD/美光/戴尔（熊市"大跌后企稳"、牛市"突破"）和7个币的突破。
晚 d 根小时线（股票按美股交易时段：7根≈1天）按当时的价进；止损/止盈/期限沿用原来那一笔的（企稳：止损用原止损，
原单已经挪到保本就用原开仓价；目标=原来的5天高点；最晚=原来的期限）。原来那一笔在这之前已经结束的，就没有"晚进"这回事，不算。
突破：晚 d 根进，止损按进场那一刻规则重新算（最近 L 根最低），出场照交易台（1R保本→跟踪3天低点）。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/jsq/pages"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np, pandas as pd
from market_data import load
_a = sys.argv; sys.argv = ["ledger.py", "--data", "/home/claude/market-data", "--jsq", "/home/claude/jsq", "--out", "/tmp/x.json"]
import ledger as LG
sys.argv = _a

NOT = 500.0
us = load.us_daily(["QQQ"]); us["date"] = pd.to_datetime(us.date); q = us.set_index("date").adj_close
bear = (q < q.rolling(200).mean()).astype(int).shift(1)          # 前一天收盘在200日线下
ndx_up = (q.diff() > 0).astype(int).shift(1)                      # 前一天纳指涨
st = load.dukascopy([x + "USUSD" for x in ["AMD", "MU", "DELL"]], start="2021-01")
SS = {}
for sym, g in st.groupby("symbol"):
    g = g.sort_values("ts").reset_index(drop=True); SS[sym.replace("USUSD", "")] = LG.session(g)

rows = []
for sym, S in SS.items():
    o, h, l, c = (S[k].to_numpy(float) for k in ["open", "high", "low", "close"]); ts = S.ts
    for e in LG.dip_episodes(S, ndx_up, bear):
        if not e["ok"] or e["ts"] < pd.Timestamp("2021-11-01", tz="UTC"): continue
        k = int(ts.searchsorted(e["ts"])); jx = int(ts.searchsorted(e["exit_ts"]))
        E0, stop0, top, R = e["entry"], e["stop0"], e["target"], e["entry"] - e["stop0"]
        for d in (0, 3, 7, 14, 21, 35):
            kk = k + d
            if kk >= len(c) - 1: continue
            if d and kk >= jx: rows.append(dict(sym=sym, ts=e["ts"], d=d, gone=True)); continue
            moved = h[k + 1:kk + 1].max() >= E0 + R if d else False
            stp = E0 if moved else stop0; E = c[kk]
            if E <= stp or E >= top: rows.append(dict(sym=sym, ts=e["ts"], d=d, gone=True)); continue
            px, j = None, kk
            for j in range(kk + 1, min(len(c), k + 71)):
                if l[j] <= stp: px = min(o[j], stp); break
                if h[j] >= E0 + R: stp = max(stp, E0)
                if h[j] >= top: px = max(o[j], top); break
            if px is None: j = min(len(c) - 1, k + 70); px = c[j]
            rows.append(dict(sym=sym, ts=e["ts"], d=d, gone=False, u=((px / E - 1) - 0.001) * NOT, rr=(top - E) / (E - stp if E > stp else np.nan), chase=(E / E0 - 1)))
D = pd.DataFrame(rows)
print("===== 熊市'大跌后企稳'（AMD/美光/戴尔，5年）：信号后晚几根进")
lab = {0: "准时", 3: "晚3小时", 7: "晚1天", 14: "晚2天", 21: "晚3天", 35: "晚5天"}
for d, x in D.groupby("d"):
    y = x[~x.gone]
    print(f"{lab[d]}：{len(x)} 次里还能进 {len(y)} 次，每次平均 {y.u.mean():+.1f}U，赚的 {(y.u > 0).mean()*100:.0f}%，"
          f"平均比准时贵 {y.chase.mean()*100:+.1f}%（前半 {y[y.ts < y.ts.quantile(.5)].u.mean():+.1f} / 后半 {y[y.ts >= y.ts.quantile(.5)].u.mean():+.1f}）")

# ---- 突破：AMD/美光/戴尔（纳指牛市，交易时段 L=7）和 7 个币（比特币50日线，L=24）
def brk_late(df, L, bpd, bull, side, ds):
    out = {}
    LS0, SS0 = LG.brk_signals(df, L)
    sig = LS0 if side == 1 else SS0
    for d in ds:
        s_ = sig.shift(d).fillna(False).astype(bool)
        z = pd.Series(False, index=df.index)
        t = LG.simulate(df, L, s_ if side == 1 else z, z if side == 1 else s_, bpd)
        if t.empty: out[d] = t; continue
        day = pd.to_datetime(t.ts, utc=True).dt.tz_convert(None).dt.normalize().to_numpy()
        b = bull.reindex(pd.DatetimeIndex(day), method="ffill").to_numpy()
        t = t[(b == 1) if side == 1 else (b == 0)]
        out[d] = t
    return out
qb = (q > q.rolling(200).mean()).astype(int).shift(1)
print("\n===== AMD/美光/戴尔 牛市突破：晚进")
acc = {}
for sym, S in SS.items():
    for d, t in brk_late(S, 7, 7, qb, 1, (0, 3, 7, 14)).items(): acc.setdefault(d, []).append(t)
for d, ts_ in acc.items():
    t = pd.concat(ts_); t = t[pd.to_datetime(t.ts, utc=True) >= pd.Timestamp("2021-11-01", tz="UTC")]
    print(f"{lab[d]}：{len(t)} 笔，每笔 {(t.r * t.R_pct * NOT).mean():+.1f}U，赚的 {(t.r > 0).mean()*100:.0f}%")
cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert(None).dt.normalize()
bc = b.groupby("day").close.last(); btc = (bc > bc.rolling(50).mean()).astype(int).shift(1)
for side, nm in ((1, "牛市突破做多"), (-1, "熊市跌破做空")):
    acc = {}
    for sym, g in cr.groupby("symbol"):
        g = g.sort_values("ts").reset_index(drop=True)
        for d, t in brk_late(g, 24, 24, btc, side, (0, 6, 24, 48)).items(): acc.setdefault(d, []).append(t)
    print(f"\n===== 7个币 {nm}：晚进")
    for d, ts_ in acc.items():
        t = pd.concat(ts_); t = t[pd.to_datetime(t.ts, utc=True) >= pd.Timestamp("2021-11-01", tz="UTC")]
        print(f"晚{d}小时：{len(t)} 笔，每笔 {(t.r * t.R_pct * NOT).mean():+.1f}U，赚的 {(t.r > 0).mean()*100:.0f}%")
