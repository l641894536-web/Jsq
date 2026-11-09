import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt")
import ep_bt as EP
u = EP.load_all()
qqq = u[u.ticker == "QQQ"].set_index("date").close; bull = (qqq > qqq.rolling(200).mean())
earn = pd.read_csv("/home/claude/fund/us/earnings.csv", parse_dates=["date"])
ek = set()
for _, r in earn.iterrows(): ek.add((r.ticker, r.date)); ek.add((r.ticker, r.date + pd.offsets.BDay(1)))
import json
perps = {p.replace("USDT", "") for p in json.load(open("/home/claude/market-data/status.json"))["stages"]["binance"].get("stock_perps", [])}

def sim_next_open(u, ev, exit_rule):
    """第二天开盘进（北京时间不用半夜等收盘），止损仍是跳空当天最低价"""
    out = []; by = {t: g.reset_index(drop=True) for t, g in u.groupby("ticker")}
    for _, e in ev.iterrows():
        g = by[e.ticker]; i = g.index[g.date == e.date][0]
        if i + 1 >= len(g): continue
        o, h, l, c = g.open.to_numpy(), g.high.to_numpy(), g.low.to_numpy(), g.close.to_numpy()
        E0 = o[i + 1]; stop = l[i]; R = E0 - stop
        if not (R > 0) or R / E0 < 0.002: continue
        ma10 = pd.Series(c).rolling(10).mean().to_numpy(); px = None
        last = min(len(c) - 1, i + 1 + (20 if exit_rule == "X1" else 60))
        for j in range(i + 1, last + 1):
            if l[j] <= stop: px = min(o[j], stop) if j > i + 1 else stop; break
            if exit_rule == "X2" and j >= i + 2 and c[j] < ma10[j]: px = c[j]; break
        if px is None: px = c[last]; j = last
        days = (g.date[j] - g.date[i + 1]).days
        ret = px / E0 - 1 - EP.COST - EP.FUND * days
        out.append(dict(ticker=e.ticker, date=e.date, ret=ret, R=ret * E0 / R, risk=R / E0))
    return pd.DataFrame(out)

for G, V in ((0.08, 3.0), (0.10, 3.0)):
    ev = EP.events(u, G, V, 1)
    ev = ev[bull.reindex(ev.date, method="ffill").to_numpy() == True]
    for xr in ("X1", "X2"):
        for nm, T in (("当天收盘进", EP.simulate(u, ev, 1, xr)), ("第二天开盘进", sim_next_open(u, ev, xr))):
            T["earn"] = [(a, b) in ek for a, b in zip(T.ticker, T.date)]; T["perp"] = T.ticker.isin(perps)
            EP.summ(f"牛市 跳空≥{G*100:.0f}% 量≥3倍 {nm} {'拿20天' if xr=='X1' else '破10日线走'}", T)
            EP.summ("   └ 币安有合约的", T[T.perp]); EP.summ("   └ 财报日", T[T.earn])
            if G == 0.08 and xr == "X2" and nm == "第二天开盘进":
                y = T.groupby(T.date.dt.year).R.agg(["mean", "size"]).round(2); print("   按年:", y.to_dict("index"))
                T.to_csv("/home/claude/bt/ep_trades_bull8_x2_nextopen.csv", index=False)
