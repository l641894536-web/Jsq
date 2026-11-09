"""熊市里怎么做？每次 100U×5倍（满仓名义 500U），扣每次成交 0.05% 和多单资金费 0.03%/天。2021-11 → 2026-10，牛熊分开、前后两段。
U1 用户的分批（澄清版）：σ=最近20天日波动
   第1笔 30%：1小时收盘比过去24小时最高跌了 1σ
   第2笔 30%：跌到第1笔再往下 3σ（"跌深了、离爆仓不远"）
   第3笔 40%：第2笔之后 24 小时内收盘反弹到第2笔上方 0.5σ（企稳）；继续跌 1σ 就不进
   第3笔进了以后才设止损：第2笔之后的最低点再下 0.5σ；没进第3笔的继续拿
   第1笔进场后 5 倍杠杆的爆仓线（按当时均价往下 19%）先到就算爆仓
   离场：回到当初24小时最高价全平；或拿满 10 天
P  恐慌后抢反弹（日线）：当天收盘比前一天跌 ≥ 2σ，收盘买满，止损 2σ，收盘站回 5 日均线或拿满 5 天就走
S  熊市反弹做空（日线）：收盘从下往上碰到 20 日均线（前一天在下面），收盘做空，止损前 5 天最高点上方 0.5σ，跌到前 10 天最低点或拿满 10 天就走"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
import exit_bt as X
import scale_in_bt as SI

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
NOTIONAL, FEE, FUND, LEV = 500.0, 0.0005, 0.0003, 5


def user_plan(df, L, bpd, sig, tz):
    df = df.sort_values("ts").reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    ts = pd.to_datetime(df.ts, utc=True)
    day = ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    S = sig.reindex(day, method="ffill").to_numpy()
    H24 = pd.Series(h).shift(1).rolling(L).max().to_numpy()
    ok = ((ts >= START) & (ts < END)).to_numpy()
    out, t, n = [], L + 1, len(c)
    while t < n - 1:
        s = S[t]
        if not (ok[t] and np.isfinite(s) and np.isfinite(H24[t]) and c[t] <= H24[t] * np.exp(-s)):
            t += 1; continue
        top, p1 = H24[t], c[t]
        p2 = p1 * np.exp(-3 * s)
        fills = [(0.3, p1)]; t2 = None; got3 = False; dead3 = False; stop = None; low2 = np.inf
        j, exit_px, liq = t + 1, None, False
        while j < n:
            w = sum(f for f, _ in fills); avg = sum(f * p for f, p in fills) / w
            liq_px = avg * (1 - 0.19)                      # 5倍逐仓粗估爆仓线
            if t2 is None and l[j] <= p2:
                fills.append((0.3, min(o[j], p2))); t2 = j
                w = sum(f for f, _ in fills); avg = sum(f * p for f, p in fills) / w; liq_px = avg * (1 - 0.19)
            if t2 is not None:
                low2 = min(low2, l[j])
            if l[j] <= liq_px:
                exit_px, liq = liq_px, True; break
            if stop is not None and l[j] <= stop:
                exit_px = min(o[j], stop); break
            if t2 is not None and not got3 and not dead3:
                if l[j] <= fills[1][1] * np.exp(-s):
                    dead3 = True
                elif c[j] >= fills[1][1] * np.exp(0.5 * s) and j - t2 <= bpd:
                    fills.append((0.4, c[j])); got3 = True; stop = low2 * np.exp(-0.5 * s)
                elif j - t2 > bpd:
                    dead3 = True
            if h[j] >= top:
                exit_px = top if o[j] < top else o[j]; break
            if j - t >= 10 * bpd or j == n - 1:
                exit_px = c[j]; break
            j += 1
        w = sum(f for f, _ in fills); avg = sum(f * p for f, p in fills) / w
        gross = w * (exit_px / avg - 1)
        cost = w * FEE * 2 + w * FUND * (j - t) / bpd
        pnl = -100.0 * w if liq else (gross - cost) * NOTIONAL     # 爆仓：投进去的保证金全没
        out.append(dict(ts=ts.iloc[t], pnl=pnl, w=w, liq=liq, days=(j - t) / bpd))
        t = j + 1
    return pd.DataFrame(out)


def daily_rules(d):
    """d: 日线 ts, open, high, low, close。返回 P 和 S 两种做法的每笔。"""
    d = d.sort_values("ts").reset_index(drop=True)
    o, h, l, c = (d[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    ts = pd.to_datetime(d.ts, utc=True)
    lr = np.r_[np.nan, np.diff(np.log(c))]
    s = pd.Series(lr).rolling(20).std().shift(1).to_numpy()
    ma5 = pd.Series(c).rolling(5).mean().to_numpy(); ma20 = pd.Series(c).rolling(20).mean().to_numpy()
    hi5 = pd.Series(h).rolling(5).max().to_numpy(); lo10 = pd.Series(l).shift(1).rolling(10).min().to_numpy()
    ok = ((ts >= START) & (ts < END)).to_numpy()
    out, n = [], len(c)
    for kind in ("P", "S"):
        i = 25
        while i < n - 1:
            if not ok[i] or not np.isfinite(s[i]):
                i += 1; continue
            if kind == "P" and lr[i] <= -2 * s[i]:
                side, E = 1, c[i]; stop = E * np.exp(-2 * s[i]); hold = 5
            elif kind == "S" and c[i] >= ma20[i] and c[i - 1] < ma20[i - 1]:
                side, E = -1, c[i]; stop = hi5[i] * np.exp(0.5 * s[i]); hold = 10
            else:
                i += 1; continue
            j, px = i + 1, None
            while j < n:
                if side == 1 and l[j] <= stop: px = min(o[j], stop); break
                if side == -1 and h[j] >= stop: px = max(o[j], stop); break
                if side == 1 and c[j] >= ma5[j]: px = c[j]; break
                if side == -1 and l[j] <= lo10[j]: px = min(o[j], lo10[j]); break
                if j - i >= hold or j == n - 1: px = c[j]; break
                j += 1
            gross = side * (px / E - 1)
            cost = FEE * 2 + (FUND * (j - i) if side == 1 else 0)
            out.append(dict(ts=ts.iloc[i], kind=kind, pnl=(gross - cost) * NOTIONAL, days=j - i))
            i = j + 1
    return pd.DataFrame(out)


def daily_from(g, weekdays, tz):
    d = g.assign(day=g.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize())
    if weekdays:
        d = d[d.day.dt.dayofweek < 5]
    d = d.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    d["ts"] = pd.to_datetime(d.day).dt.tz_localize("UTC")
    return d


if __name__ == "__main__":
    us = load.us_daily(["GC=F", "SI=F", "QQQ", "AMD", "MU", "DELL"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    sets = []
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        g = dk[dk.symbol == sym]
        sets.append((grp, sym, g, 24, 24, X.bull_daily(px[fut]), "America/New_York", daily_from(g, True, "America/New_York")))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = X.bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        sets.append(("加密(BTC/ETH/SOL)", sym, g, 24, 24, btc, "UTC", daily_from(g, False, "UTC")))
    st = load.dukascopy([s + "USUSD" for s in ["AMD", "MU", "DELL"]], start="2021-06")
    for sym, g in st.groupby("symbol"):
        tk = sym.replace("USUSD", "")
        d = us[us.ticker == tk].assign(ts=lambda x: pd.to_datetime(x.date).dt.tz_localize("UTC"))[["ts", "open", "high", "low", "close"]]
        sets.append(("AMD/美光/戴尔", tk, g, 7, 7, X.bull_daily(px["QQQ"]), "America/New_York", d))
    rows = []
    allt = []
    for grp, sym, g, L, bpd, bull, tz, d in sets:
        u = user_plan(g[["ts", "open", "high", "low", "close"]], L, bpd, SI.daily_sigma(g, tz), tz).assign(kind="U")
        dr = daily_rules(d[["ts", "open", "high", "low", "close"]])
        t = pd.concat([u, dr], ignore_index=True)
        day = t.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
        bb = bull.reindex(day, method="ffill").to_numpy()
        t["env"] = np.where(pd.isna(bb), None, np.where(bb == 1, "牛市", "熊市"))
        allt.append(t.assign(grp=grp, sym=sym))
    T = pd.concat(allt, ignore_index=True); T = T[T.env.notna()]
    T["half"] = np.where(T.ts < MID, "前段", "后段")
    T.to_csv("bear_strats_trades.csv", index=False)
    NM = {"U": "你的分批(补到深处)", "P": "恐慌大跌抢反弹", "S": "反弹到20日线做空"}
    for (g, e, k), x in T.groupby(["grp", "env", "kind"]):
        hm = x.groupby("half").pnl.mean()
        rows.append(dict(品种=g, 环境=e, 做法=NM[k], 次数=len(x), 每次平均U=round(x.pnl.mean(), 2), 前段=round(hm.get("前段", np.nan), 2), 后段=round(hm.get("后段", np.nan), 2),
                         赚的比例=round((x.pnl > 0).mean() * 100), 最差一次U=round(x.pnl.min(), 1), 爆仓次数=int(x.liq.fillna(False).sum()) if "liq" in x else 0))
    pd.set_option("display.width", 250)
    R = pd.DataFrame(rows).sort_values(["环境", "品种", "做法"])
    print(R.to_string(index=False))
