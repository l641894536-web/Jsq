"""大区间（箱体）高抛低吸：4小时线 5天/10天 区间，日线 10天/20天 区间。做法同 range_bt.py：
震荡识别 ER<0.3、宽度 3~12 倍 ATR（该周期的 ATR）；touch / reclaim 两种进场；止损区间外 0.3ATR；中线平一半保本、对边平剩下；
最多拿：4小时 10天、日线 20天。成本：来回 0.1% + 多单资金费 0.03%/天（币安永续常见水平，空单不扣）。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
from market_data.config import DK_STOCKS_1H_OTHER
import pandas as pd, numpy as np
import range_bt as RB

FUND = 0.0003


def sim(df, N, maxbars, bars_per_day):
    t = RB.sim(df, N, maxbars)
    if t.empty:
        return t
    E_cost = RB.COST
    # RB.sim 已扣来回 0.1%；这里再按持有天数给多单加资金费
    days = t.bars / bars_per_day
    t["r"] = t.r - np.where(t.side == 1, FUND * days / t.R_pct, 0.0)
    return t


def resample(df, rule):
    g = df.set_index("ts").resample(rule, label="left", closed="left")
    return g.agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()


def run():
    out = []
    us = load.us_daily(["GC=F", "SI=F", "QQQ", "^GSPC"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")

    def add(grp, sym, h1, bpd4, daily, bull, tz):
        g4 = resample(h1[["ts", "open", "high", "low", "close"]], "4h")
        for N, nm in [(5 * bpd4, "4小时·5天箱"), (10 * bpd4, "4小时·10天箱")]:
            out.append(RB.tag(sim(g4, N, 10 * bpd4, bpd4), bull, tz).assign(grp=grp, sym=sym, win=nm))
        for N, nm in [(10, "日线·10天箱"), (20, "日线·20天箱")]:
            out.append(RB.tag(sim(daily, N, 20, 1), bull, tz).assign(grp=grp, sym=sym, win=nm))

    def daily_from(h1, weekdays, tz):
        d = h1.assign(day=h1.ts.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize())
        if weekdays:
            d = d[d.day.dt.dayofweek < 5]
        d = d.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
        d["ts"] = pd.to_datetime(d.day).dt.tz_localize("UTC")
        return d[["ts", "open", "high", "low", "close"]]

    dk = load.dukascopy(["XAUUSD", "XAGUSD", "XPTCMDUSD", "XPDCMDUSD", "COPPERCMDUSD", "GASCMDUSD"], start="2020-10")
    for sym, g in dk.groupby("symbol"):
        grp = {"XAUUSD": "黄金", "XAGUSD": "白银"}.get(sym, "铂钯铜天然气")
        d = daily_from(g, True, "America/New_York")
        bull = RB.bull_daily(px["GC=F"] if sym == "XAUUSD" else px["SI=F"] if sym == "XAGUSD" else d.set_index(d.ts.dt.tz_localize(None)).close)
        add(grp, sym, g, 6, d, bull, "America/New_York")
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2020-10")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = RB.bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        add("加密", sym, g, 6, daily_from(g, False, "UTC"), btc, "UTC")
    main3 = ["AMD", "MU", "DELL"]
    tech = ["AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX", "MRVL",
            "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN"]
    st = load.dukascopy([s + "USUSD" for s in main3 + tech + DK_STOCKS_1H_OTHER], start="2020-10")
    usd = load.us_daily(main3 + tech + DK_STOCKS_1H_OTHER, start="2020-06-01")
    for sym, g in st.groupby("symbol"):
        tk = sym.replace("USUSD", "")
        grp = "AMD/美光/戴尔" if tk in main3 else ("其他科技股" if tk in tech else "非科技股")
        d = usd[usd.ticker == tk].assign(ts=lambda x: pd.to_datetime(x.date).dt.tz_localize("UTC"))[["ts", "open", "high", "low", "close"]]
        add(grp, tk, g, 2, d, RB.bull_daily(px["^GSPC"] if grp == "非科技股" else px["QQQ"]), "America/New_York")
    t = pd.concat(out, ignore_index=True)
    t["half"] = np.where(pd.to_datetime(t.ts, utc=True) < RB.MID, "h1", "h2")
    t["state"] = np.where(t.er < 0.3, "震荡", "有方向")
    t.to_csv("range_big_trades.csv", index=False)
    return t


if __name__ == "__main__":
    t = run() if "--cached" not in sys.argv else pd.read_csv("range_big_trades.csv")
    pd.set_option("display.width", 250)
    x = t[t.state == "震荡"]
    g = x.groupby(["grp", "win"])
    rep = pd.DataFrame({"笔数": g.size(), "胜率": g.r.apply(lambda r: round((r > 0).mean() * 100)),
                        "不算成本": g.r_gross.mean().round(3), "扣成本": g.r.mean().round(3),
                        "先打止损%": g.r_gross.apply(lambda r: round((r <= -0.9).mean() * 100)),
                        "持有天中位": g.apply(lambda d: d.bars.median()).round(0)})
    rep = rep.join(x.groupby(["grp", "win", "half"]).r.mean().unstack().round(3))
    print(rep.to_string())
    print("\n扣成本每笔R，按牛熊×方向（只看震荡）")
    x = x.assign(dir=np.where(x.side == 1, "多", "空"))
    print(x.groupby(["grp", "win", "env", "dir"]).r.agg(["size", "mean"]).round(3).unstack(["env", "dir"]).to_string())
