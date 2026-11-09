"""震荡期高抛低吸：先用开单前就知道的条件识别"震荡"，再做区间两端。按品种分开。
区间 = 前 N 根小时线（不含当前）的最高 H / 最低 L，宽度 W = H − L。N：24小时品种 24 根(1天) / 72 根(3天)；美股时段 7 / 21。
震荡识别：效率比 ER = |N根净移动| / N根逐根涨跌绝对值之和 < 0.3（来回走、没走出方向），且 3·ATR ≤ W ≤ 12·ATR。
          对照组：同样的进场，但 ER ≥ 0.3（有方向时）——看"识别震荡"有没有用。
进场（收盘确认）：
  touch  收盘回到区间下沿 20% 以内、仍在区间里、这根收阳 → 做多；上沿对称做空
  reclaim 盘中跌破 L、收盘收回 L 上方（假跌破）→ 做多；假突破对称做空
止损：区间外 0.3·ATR（和本根极值取更远的）。出场：到区间中线平一半、止损挪保本；剩下到对边（离对边 10% W）平掉；最多拿 3 天。
扣来回 0.1%。2021-11 → 2026-10，2024-05 前后分两段。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
from market_data.config import DK_STOCKS_1H_OTHER
import pandas as pd, numpy as np

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
COST = 0.001


def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.empty_like(tr); a[0] = tr[0]
    for i in range(1, len(tr)):
        a[i] = a[i - 1] + (tr[i] - a[i - 1]) / 14
    return a


def sim(df, N, maxbars, buf=0.3):
    df = df.sort_values("ts").reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    ts = pd.to_datetime(df.ts, utc=True)
    a = atr14(h, l, c)
    H = pd.Series(h).shift(1).rolling(N).max().to_numpy()
    L = pd.Series(l).shift(1).rolling(N).min().to_numpy()
    d = np.abs(np.diff(c, prepend=c[0]))
    path = pd.Series(d).rolling(N).sum().to_numpy()
    er = np.abs(c - np.r_[np.full(N, np.nan), c[:-N]]) / np.where(path > 0, path, np.nan)
    ok = ((ts >= START) & (ts < END)).to_numpy()
    out = []
    n = len(c)
    for kind in ("touch", "reclaim"):
        busy = -1
        for t in range(N + 1, n - 1):
            if t <= busy or not ok[t]:
                continue
            W = H[t] - L[t]
            if not (np.isfinite(W) and np.isfinite(er[t]) and 3 * a[t] <= W <= 12 * a[t]):
                continue
            side = 0
            if kind == "touch":
                if L[t] < c[t] <= L[t] + 0.2 * W and c[t] > o[t]: side = 1
                elif H[t] - 0.2 * W <= c[t] < H[t] and c[t] < o[t]: side = -1
            else:
                if l[t] < L[t] < c[t] < L[t] + 0.5 * W: side = 1
                elif h[t] > H[t] > c[t] > H[t] - 0.5 * W: side = -1
            if side == 0:
                continue
            E0 = c[t]
            stop = (min(L[t], l[t]) - buf * a[t]) if side == 1 else (max(H[t], h[t]) + buf * a[t])
            R = side * (E0 - stop)
            mid = L[t] + 0.5 * W
            far = (H[t] - 0.1 * W) if side == 1 else (L[t] + 0.1 * W)
            if not (R > 0) or side * (mid - E0) <= 0:
                continue
            pos, real, j = 1.0, 0.0, t + 1
            while j < n:
                adv = l[j] if side == 1 else h[j]
                fav = h[j] if side == 1 else l[j]
                if side * (adv - stop) <= 0:
                    px = stop if side * (o[j] - stop) > 0 else o[j]
                    real += pos * side * (px - E0) / R; pos = 0; break
                if pos == 1.0 and side * (fav - mid) >= 0:
                    real += 0.5 * side * (mid - E0) / R; pos = 0.5
                    stop = E0 if side == 1 else E0
                    stop = max(stop, E0) if side == 1 else min(stop, E0)
                if pos == 0.5 and side * (fav - far) >= 0:
                    real += 0.5 * side * (far - E0) / R; pos = 0; break
                if j - t >= maxbars or j == n - 1:
                    real += pos * side * (c[j] - E0) / R; pos = 0; break
                j += 1
            busy = j
            out.append(dict(ts=ts.iloc[t], kind=kind, side=side, er=er[t], r=real - COST * E0 / R, r_gross=real, R_pct=R / E0, bars=j - t))
    return pd.DataFrame(out)


def bull_daily(close):
    close = close.dropna()
    return (close > close.rolling(200).mean()).astype(float).where(close.rolling(200).count() >= 200).shift(1)


def tag(t, bull, tz):
    if t.empty:
        return t
    day = t.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    b = bull.reindex(day, method="ffill").to_numpy()
    t = t.assign(env=np.where(pd.isna(b), None, np.where(b == 1, "bull", "bear")))
    return t[t.env.notna()]


def run():
    out = []
    us = load.us_daily(["GC=F", "SI=F", "QQQ", "^GSPC"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")

    def add(grp, sym, g, Ns, bpd, bull, tz):
        for N, nm in zip(Ns, ["1天", "3天"]):
            t = sim(g[["ts", "open", "high", "low", "close"]], N, 3 * bpd)
            out.append(tag(t, bull, tz).assign(grp=grp, sym=sym, win=nm))

    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        add(grp, sym, dk[dk.symbol == sym], (24, 72), 24, bull_daily(px[fut]), "America/New_York")
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        add("加密", sym, g, (24, 72), 24, btc, "UTC")
    main3 = ["AMD", "MU", "DELL"]
    tech = ["AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX", "MRVL",
            "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN"]
    st = load.dukascopy([s + "USUSD" for s in main3 + tech + DK_STOCKS_1H_OTHER], start="2021-06")
    for sym, g in st.groupby("symbol"):
        tk = sym.replace("USUSD", "")
        grp = "AMD/美光/戴尔" if tk in main3 else ("其他科技股" if tk in tech else "非科技股")
        add(grp, tk, g, (7, 21), 7, bull_daily(px["^GSPC"] if grp == "非科技股" else px["QQQ"]), "America/New_York")
    cm = load.dukascopy(["XPTCMDUSD", "XPDCMDUSD", "COPPERCMDUSD", "GASCMDUSD"], start="2021-06")
    for sym, g in cm.groupby("symbol"):
        d = g.assign(day=g.ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize())
        d = d[d.day.dt.dayofweek < 5].groupby("day").close.last()
        add("铂钯铜天然气", sym, g, (24, 72), 23, bull_daily(d), "America/New_York")
    t = pd.concat(out, ignore_index=True)
    t["half"] = np.where(t.ts < MID, "h1", "h2")
    t["state"] = np.where(t.er < 0.3, "震荡", "有方向")
    t["dir"] = np.where(t.side == 1, "long", "short")
    t.to_csv("range_trades.csv", index=False)
    return t


if __name__ == "__main__":
    t = run() if "--cached" not in sys.argv else pd.read_csv("range_trades.csv")
    pd.set_option("display.width", 250)
    g = t.groupby(["grp", "win", "kind", "state"])
    rep = g.r.agg(笔数="size", 胜率=lambda x: round((x > 0).mean() * 100), 每笔R="mean").round(3)
    rep["不算成本"] = g.r_gross.mean().round(3)
    rep = rep.join(t.groupby(["grp", "win", "kind", "state", "half"]).r.mean().unstack("half").round(3))
    rep["持有中位(根)"] = g.bars.median()
    print(rep.to_string())
