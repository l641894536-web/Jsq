"""同一个进场（顺小时线趋势、收盘突破前24小时高/低点），只比较出场方式，按品种分开：
  A  只放初始止损，拿到小时线趋势反转或10天
  E  浮盈1R挪保本（结论卡现在的统计口径）
  D  1.5R 全部止盈              G  2R 全部止盈（1R后保本）          ← 固定目标
  C  1R后保本，再跟着"过去24小时最低点"往上挪（全仓跟踪）
  F  1R后保本，跟着"过去3天最低点"往上挪
  B  1R先平一半，剩下保本+跟踪24小时最低点
  I  1R先平一半，剩下保本+跟踪3天最低点
  H  2R先平一半（1R后保本），剩下跟踪24小时最低点
  J  2R先平一半（1R后保本），剩下跟踪3天最低点
做空完全对称。扣来回0.1%。2021-11 → 2026-10，2024-05 前后分两段。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
from contract_bt import simulate

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))
VARS = ["A", "E", "D", "G", "C", "F", "B", "I", "H", "J"]


def bull_daily(close):
    close = close.dropna()
    return (close > close.rolling(200).mean()).astype(float).where(close.rolling(200).count() >= 200).shift(1)


def tagged(t, bull, tz="America/New_York"):
    if t.empty:
        return t
    ts = pd.to_datetime(t.ts, utc=True)
    t = t[(ts >= START) & (ts < END)].copy()
    day = pd.to_datetime(t.ts, utc=True).dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    b = bull.reindex(day, method="ffill").to_numpy()
    t["env"] = np.where(pd.isna(b), None, np.where(b == 1, "bull", "bear"))
    t["dir"] = np.where(t.side == 1, "long", "short")
    t["half"] = np.where(pd.to_datetime(t.ts, utc=True) < MID, "h1", "h2")
    return t[t.env.notna()]


def run():
    out = []
    us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        g = dk[dk.symbol == sym].sort_values("ts").reset_index(drop=True)
        for v in VARS:
            out.append(tagged(simulate(g, 24, v, entry="breakout", bars_per_day=24), bull_daily(px[fut])).assign(grp=grp, sym=sym, v=v))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        g = g.sort_values("ts").reset_index(drop=True)
        for v in VARS:
            out.append(tagged(simulate(g, 24, v, entry="breakout", bars_per_day=24), btc, "UTC").assign(grp="加密", sym=sym, v=v))
    main3 = ["AMD", "MU", "DELL"]
    tech = ["AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX", "MRVL",
            "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN"]
    st = load.dukascopy([s + "USUSD" for s in main3 + tech], start="2021-06")
    qqq = bull_daily(px["QQQ"])
    for sym, g in st.groupby("symbol"):
        tk = sym.replace("USUSD", "")
        g = g.sort_values("ts").reset_index(drop=True)
        for v in VARS:
            out.append(tagged(simulate(g, 7, v, entry="breakout", bars_per_day=7), qqq).assign(grp="AMD/美光/戴尔" if tk in main3 else "其他科技股", sym=tk, v=v))
    t = pd.concat(out, ignore_index=True)
    t.to_csv("exit_trades.csv", index=False)
    return t


def report(t):
    rows = []
    for (grp, env, d, v), x in t.groupby(["grp", "env", "dir", "v"]):
        reach = x.mfe >= 1
        hm = x.groupby("half").r.mean()
        rows.append(dict(品种=grp, 环境=env, 方向=d, 出场=v, 笔数=len(x), 胜率=round((x.r > 0).mean() * 100), 每笔R=round(x.r.mean(), 3),
                         前段=round(hm.get("h1", np.nan), 3), 后段=round(hm.get("h2", np.nan), 3),
                         赚的平均=round(x.r[x.r > 0].mean(), 2), 最大单笔=round(x.r.max(), 1),
                         到过1R又亏=round(((x.r_gross < 0) & reach).sum() / max(reach.sum(), 1) * 100)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    t = run() if "--cached" not in sys.argv else pd.read_csv("exit_trades.csv")
    R = report(t)
    R.to_csv("exit_report.csv", index=False)
    pd.set_option("display.width", 250)
    for (grp, env, d), x in R.groupby(["品种", "环境", "方向"], sort=False):
        if x.笔数.iloc[0] < 60:
            continue
        print(f"\n== {grp} · {'牛市' if env == 'bull' else '熊市'} · {'做多' if d == 'long' else '做空'}")
        print(x.set_index("出场").loc[VARS].drop(columns=["品种", "环境", "方向"]).to_string())
