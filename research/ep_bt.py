"""美股'财报/消息跳空'（Kullamägi 的 episodic pivot）回测，2021-11 → 2026-10，日线。
事件：今天开盘比昨天收盘高 ≥ G%，成交量 ≥ 过去50天平均的 V 倍（放量）。跳空向下（做空）对称测试。
进场：跳空当天收盘价（E1 全部 / E2 只要收在当天振幅上半部）。止损：跳空当天最低价（做空=最高价），从第二天起盘中触发。
离场：X1 拿满20个交易日；X2 收盘跌破10日均线就走（最多60天）。每笔记录 R（=赚的 ÷ 进场到止损的距离）和涨跌幅。
费用：来回 0.1%，多单资金费 0.03%/天（按合约做）。
对照：同一批股票随机挑日子、同样的止损和离场（'随便开单'）；只跳空不放量；牛熊（QQQ 200日线）、前后两段、有没有财报。
用法：python3 ep_bt.py"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np

START, MID, END = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-01"), pd.Timestamp("2026-10-31")
COST, FUND = 0.001, 0.0003


def load_all():
    u = load.us_daily()
    u = u[~u.ticker.str.contains(r"\^|=|-|\.")].copy()
    u["date"] = pd.to_datetime(u.date)
    u = u[u.date >= "2020-09-01"].sort_values(["ticker", "date"])
    return u


def events(u, G=0.08, V=3.0, side=1):
    g = u.groupby("ticker", group_keys=False)
    u = u.assign(pc=g.close.shift(1), v50=g.volume.transform(lambda x: x.rolling(50).mean().shift(1)))
    gap = u.open / u.pc - 1
    m = (side * gap >= G) & (u.volume >= V * u.v50) & (u.date >= START) & (u.date <= END) & (u.pc > 3)
    return u[m]


def simulate(u, ev, side=1, exit_rule="X1", upper_only=False):
    out = []
    by = {t: g.reset_index(drop=True) for t, g in u.groupby("ticker")}
    idx = {t: pd.Index(g.date) for t, g in by.items()}
    for _, e in ev.iterrows():
        g = by[e.ticker]; i = idx[e.ticker].get_loc(e.date)
        o, h, l, c = g.open.to_numpy(), g.high.to_numpy(), g.low.to_numpy(), g.close.to_numpy()
        if upper_only and h[i] > l[i] and side * ((c[i] - l[i]) / (h[i] - l[i]) - 0.5) < 0: continue
        E0 = c[i]; stop = l[i] if side == 1 else h[i]; R = side * (E0 - stop)
        if not (R > 0) or R / E0 < 0.002: continue
        ma10 = pd.Series(c).rolling(10).mean().to_numpy()
        px, j, why = None, None, ""
        last = min(len(c) - 1, i + (20 if exit_rule == "X1" else 60))
        if last <= i: continue
        for j in range(i + 1, last + 1):
            if side * (l[j] if side == 1 else h[j]) <= side * stop:
                px = min(o[j], stop) if side == 1 else max(o[j], stop); why = "止损"; break
            if exit_rule == "X2" and j >= i + 2 and side * (c[j] - ma10[j]) < 0:
                px = c[j]; why = "破10日线"; break
        if px is None: px = c[last]; j = last; why = "到期"
        days = (g.date[j] - g.date[i]).days
        ret = side * (px / E0 - 1) - COST - (FUND * days if side == 1 else 0)
        out.append(dict(ticker=e.ticker, date=e.date, ret=ret, R=ret * E0 / R, risk=R / E0, days=days, why=why))
    return pd.DataFrame(out)


def summ(nm, T):
    if T.empty: print(f"{nm}: 无"); return
    h = T.groupby(T.date < MID)["R"].mean()
    print(f"{nm:<40} {len(T):5d}笔 平均每笔 {T.R.mean():+.2f}R / {T.ret.mean()*100:+.2f}%  赚的 {(T.ret > 0).mean()*100:.0f}%  前段 {h.get(True, np.nan):+.2f}R 后段 {h.get(False, np.nan):+.2f}R  止损距离中位 {T.risk.median()*100:.1f}%")


if __name__ == "__main__":
    u = load_all()
    qqq = u[u.ticker == "QQQ"].set_index("date").close; bull = (qqq > qqq.rolling(200).mean())
    perps = {p.replace("USDT", "") for p in __import__("json").load(open("/home/claude/market-data/status.json"))["stages"]["binance"].get("stock_perps", [])}
    earn = pd.read_csv("/home/claude/fund/us/earnings.csv", parse_dates=["date"])
    ekeys = set()
    for _, r in earn.iterrows():
        ekeys.add((r.ticker, r.date)); ekeys.add((r.ticker, r.date + pd.offsets.BDay(1)))
    rng = np.random.default_rng(0)
    res = {}
    for side, sname in ((1, "跳空向上做多"), (-1, "跳空向下做空")):
        for G, V in ((0.05, 2.0), (0.08, 3.0), (0.10, 3.0)):
            ev = events(u, G, V, side)
            for xr in ("X1", "X2"):
                T = simulate(u, ev, side, xr)
                T["bull"] = bull.reindex(T.date, method="ffill").to_numpy()
                T["perp"] = T.ticker.isin(perps); T["earn"] = [(a, b) in ekeys for a, b in zip(T.ticker, T.date)]
                res[(side, G, V, xr)] = T
                summ(f"{sname} 跳空≥{G*100:.0f}% 量≥{V:.0f}倍 {'拿20天' if xr == 'X1' else '破10日线走'}", T)
                summ("   └ 纳指牛市", T[T.bull == True]); summ("   └ 纳指熊市", T[T.bull == False])
                summ("   └ 币安有合约的股票", T[T.perp]); summ("   └ 已知是财报日", T[T.earn])
        # 对照：只跳空不放量；随机日子
        ev = events(u, 0.08, 0.0, side); summ(f"{sname} 对照：跳空≥8%不看量 拿20天", simulate(u, ev, side, "X1"))
        pool = u[(u.date >= START) & (u.date <= END - pd.Timedelta(days=40))]
        rnd = pool.sample(4000, random_state=1)
        summ(f"{sname} 对照：随机日子 拿20天", simulate(u, rnd, side, "X1"))
        summ(f"{sname} 对照：随机日子 破10日线走", simulate(u, rnd, side, "X2"))
    import pickle; pickle.dump(res, open("/home/claude/bt/ep_res.pkl", "wb"))
