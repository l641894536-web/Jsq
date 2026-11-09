"""止损放宽会不会更好？同一个突破进场（出场 F：1R保本+跟踪3天低点），止损四种：
  基准：24小时最低点外0.1%；+1ATR / +2ATR：再往外1/2倍小时ATR；3天低点：过去3天最低点外0.1%。
区间单（range_bt 的 touch，3天区间、只在震荡里）止损：区间外 0.3 / 1 / 2 倍ATR。扣成本口径不变。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
import pandas as pd, numpy as np
from market_data import load
from contract_bt import simulate
import exit_bt as X

VARS = [("基准24h低点", None, 0.0), ("24h低点+1ATR", None, 1.0), ("24h低点+2ATR", None, 2.0), ("3天低点", 3, 0.0)]


def run():
    out = []
    us = load.us_daily(["GC=F", "SI=F", "QQQ"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    sets = []
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-06")
    for sym, fut, grp in [("XAUUSD", "GC=F", "黄金"), ("XAGUSD", "SI=F", "白银")]:
        sets.append((grp, sym, dk[dk.symbol == sym].sort_values("ts").reset_index(drop=True), 24, X.bull_daily(px[fut]), "America/New_York"))
    cr = load.binance("1h", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"], start="2021-06")
    b = cr[cr.symbol == "BTCUSDT"].copy(); b["day"] = b.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    btc = X.bull_daily(b.groupby("day").close.last())
    for sym, g in cr.groupby("symbol"):
        sets.append(("加密", sym, g.sort_values("ts").reset_index(drop=True), 24, btc, "UTC"))
    st = load.dukascopy([s + "USUSD" for s in ["AMD", "MU", "DELL"]], start="2021-06")
    for sym, g in st.groupby("symbol"):
        sets.append(("AMD/美光/戴尔", sym, g.sort_values("ts").reset_index(drop=True), 7, X.bull_daily(px["QQQ"]), "America/New_York"))
    for grp, sym, g, L, bull, tz in sets:
        for nm, sl, sa in VARS:
            t = simulate(g, L, "F", entry="breakout", bars_per_day=L, stop_L=(sl * L if sl else None), stop_atr=sa, max_risk=0.2)
            out.append(X.tagged(t, bull, tz).assign(grp=grp, sym=sym, stopv=nm))
    return pd.concat(out, ignore_index=True)


if __name__ == "__main__":
    t = run()
    t.to_csv("stopwidth_trades.csv", index=False)
    rows = []
    for (g, e, d, v), x in t.groupby(["grp", "env", "dir", "stopv"]):
        hm = x.groupby("half").r.mean()
        rows.append(dict(品种=g, 环境=e, 方向=d, 止损=v, 笔数=len(x), 止损占价格=round(x.R_pct.median() * 100, 2),
                         胜率=round((x.r > 0).mean() * 100), 每笔R=round(x.r.mean(), 3), 前段=round(hm.get("h1", np.nan), 3), 后段=round(hm.get("h2", np.nan), 3),
                         每笔占价格=round((x.r * x.R_pct).mean() * 100, 3)))
    R = pd.DataFrame(rows)
    order = [v[0] for v in VARS]
    for key in [("黄金", "bull", "long"), ("白银", "bull", "long"), ("加密", "bull", "long"), ("加密", "bear", "long"), ("AMD/美光/戴尔", "bull", "long"), ("黄金", "bull", "short"), ("AMD/美光/戴尔", "bull", "short")]:
        x = R[(R.品种 == key[0]) & (R.环境 == key[1]) & (R.方向 == key[2])].set_index("止损").loc[order]
        print(f"\n== {key[0]} · {'牛市' if key[1] == 'bull' else '熊市'} · {'做多' if key[2] == 'long' else '做空'}")
        print(x.drop(columns=["品种", "环境", "方向"]).to_string())
