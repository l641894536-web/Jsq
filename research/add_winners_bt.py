"""赚钱的单子怎么加仓：先开100U，涨了再加（总仓位变大），和"开了100就是100"比。
入场：所有顺势突破（金、银、7个币、AMD/美光/戴尔；不分牛熊，代表"顺着走势开的单"），止损=最近 L 根低点。
出场：交易台的出场（1R 保本→跟踪3天低点、小时线趋势反转、最多10天），加的仓和底仓一起走。
加仓方案（每次加仓按加仓价成交，扣0.1%手续费）：
  不加       100U
  等额加     +1R 加100U（全部止损挪到开仓价），+2R 再加100U（全部止损挪到 +1R 那个价）
  递减加     +1R 加60U，+2R 加40U（止损同上）
  只加一次   +1R 加100U
  亏了加     -0.5R 加100U、-0.8R 再加100U（拉均价，止损不变）——你以前的做法，对照用
U 都按 5 倍杠杆：100U 保证金 = 500U 持仓价值。
"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); os.environ["MARKET_DATA"] = "/home/claude/market-data"
import numpy as np, pandas as pd
from market_data import load


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


SCHEMES = {
    "不加": [],
    "等额加": [(1.0, 100), (2.0, 100)],
    "递减加": [(1.0, 60), (2.0, 40)],
    "只加一次": [(1.0, 100)],
    "亏了加(拉均价)": [(-0.5, 100), (-0.8, 100)],
}


def run(df, L, side, scheme, start):
    c, h, l, o = (df[k].to_numpy(float) for k in ["close", "high", "low", "open"])
    up = (ema(df.close, 20) > ema(df.close, 50)).to_numpy()
    hi = df.high.rolling(L).max().shift(1).to_numpy(); lo = df.low.rolling(L).min().shift(1).to_numpy()
    cs = df.close.to_numpy()
    sig = (up & (cs > hi) & (cs > np.roll(cs, L))) if side == 1 else (~up & (cs < lo) & (cs < np.roll(cs, L)))
    out, i, n = [], max(L + 1, 60), len(c)
    t0 = df.ts.searchsorted(pd.Timestamp(start, tz="UTC"))
    i = max(i, t0)
    adds = SCHEMES[scheme]
    while i < n - 1:
        if not sig[i]: i += 1; continue
        E = c[i]; stop0 = (l[i - L + 1:i + 1].min() * 0.999) if side == 1 else (h[i - L + 1:i + 1].max() * 1.001); R = side * (E - stop0)
        if not (0.004 * E <= R <= 0.08 * E): i += 1; continue
        legs = [(E, 100.0)]; done = [False] * len(adds); st = stop0; armed = False; mfe = 0.0; px = None; j = i + 1
        def try_adds(j, want_profit):
            nonlocal st, armed
            for a_, (k, sz) in enumerate(adds):
                if done[a_] or (k > 0) != want_profit: continue
                lvl = E + side * k * R; d = side * np.sign(k)
                hit = h[j] >= lvl if d > 0 else l[j] <= lvl
                if not hit or side * (lvl - st) <= 0: continue
                fill = max(lvl, o[j]) if d > 0 else min(lvl, o[j])
                legs.append((fill, float(sz))); done[a_] = True
                if k > 0:
                    nst = E + side * (k - 1) * R; st = max(st, nst) if side == 1 else min(st, nst); armed = True
        while j < n:
            try_adds(j, False)                                   # 亏了加：价格先经过加仓价，再到止损
            adv = l[j] if side == 1 else h[j]
            if side * (adv - st) <= 0: px = st if side * (o[j] - st) > 0 else o[j]; break
            try_adds(j, True)                                    # 赚了加：同一根先碰止损就不算加上
            mfe = max(mfe, side * ((h[j] if side == 1 else l[j]) - E) / R)
            if mfe >= 1: armed = True
            if armed:
                tr = l[max(0, j - 3 * L + 1):j + 1].min() * 0.999 if side == 1 else h[max(0, j - 3 * L + 1):j + 1].max() * 1.001
                st = max(st, E, tr) if side == 1 else min(st, E, tr)
            if (side == 1 and not up[j] and up[j - 1]) or (side == -1 and up[j] and not up[j - 1]) or j - i >= 10 * (L if L == 7 else 24): px = c[j]; break
            j += 1
        if px is None: break
        u = sum(5 * m * (side * (px - e) / e - 0.001) for e, m in legs)
        out.append(dict(ts=df.ts.iloc[i], u=u, legs=len(legs), margin=sum(m for _, m in legs)))
        i = j + 1
    return out


def main():
    data = []
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, g in dk.groupby("symbol"): data.append(("金银", sym, g.sort_values("ts").reset_index(drop=True), 24))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
    for sym, g in cr.groupby("symbol"): data.append(("币", sym, g.sort_values("ts").reset_index(drop=True), 24))
    st = load.dukascopy([x + "USUSD" for x in ["AMD", "MU", "DELL"]], start="2021-06")
    for sym, g in st.groupby("symbol"):
        g = g.sort_values("ts").reset_index(drop=True); ny = g.ts.dt.tz_convert("America/New_York")
        data.append(("股票", sym, g[(ny.dt.weekday < 5) & (ny.dt.hour >= 9) & (ny.dt.hour <= 15)].reset_index(drop=True), 7))
    rows = []
    for grp, sym, df, L in data:
        for side in (1, -1):
            for sc in SCHEMES:
                for t in run(df, L, side, sc, "2021-11-01"): rows.append(dict(t, grp=grp, sym=sym, side=side, sc=sc))
    T = pd.DataFrame(rows); T.to_csv("/home/claude/bt/add_winners_trades.csv.gz", index=False)
    mid = T.ts.quantile(0.5)
    out = []
    for (grp, side, sc), x in T.groupby(["grp", "side", "sc"]):
        out.append(dict(组=grp, 方向="多" if side == 1 else "空", 加法=sc, 笔数=len(x), 每笔U=round(x.u.mean(), 2), 赚的=f"{(x.u > 0).mean()*100:.0f}%",
                        最差一笔=round(x.u.min()), 最好一笔=round(x.u.max()), 前半=round(x[x.ts < mid].u.mean(), 2), 后半=round(x[x.ts >= mid].u.mean(), 2),
                        加过仓的比例=f"{(x.legs > 1).mean()*100:.0f}%"))
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(pd.DataFrame(out).to_string(index=False))
    print("\n全部合起来：")
    print(T.groupby("sc").u.agg(["count", "mean", "min", "max"]).round(2).to_string())


if __name__ == "__main__":
    main()
