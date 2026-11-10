"""对账：交易台页面的突破信号（card.js 的 brk）和回测 contract_bt.simulate（出场F）在同一批K线上，进场时间和价格必须完全一致。
用法：先 node /home/claude/shot/parity.js（把页面算出的交易写到 /tmp/js_trades.json），再 python3 parity_check.py"""
import json, sys, pandas as pd
sys.path.insert(0, "/home/claude/bt")
import contract_bt as CB
FX = json.load(open("/home/claude/shot/fx.json")); JS = json.load(open("/tmp/js_trades.json"))
def bars(sym, stock):
    d = pd.DataFrame(FX[f"{sym}|1h"][:-1]).iloc[:, :5]; d.columns = ["t", "open", "high", "low", "close"]; d = d.astype(float)
    d["ts"] = pd.to_datetime(d.t, unit="ms", utc=True)
    if stock:
        ny = d.ts.dt.tz_convert("America/New_York"); d = d[(ny.dt.dayofweek < 5) & (ny.dt.hour >= 9) & (ny.dt.hour <= 15)]
    return d.reset_index(drop=True)
import numpy as np, indicator_bt as IB
def day_trend(sym, d, stock):
    """和页面 needD1/dayTrendAt 同一算法：币安1d（去掉未收盘的最后一根；股票去掉周末），50日均线上方且均线比5天前高=+1"""
    k = pd.DataFrame(FX[f"{sym}|1d"][:-1]).iloc[:, [0, 4]].astype(float); k.columns = ["t", "c"]
    if stock: k = k[pd.to_datetime(k.t, unit="ms", utc=True).dt.dayofweek < 5].reset_index(drop=True)
    m = k.c.rolling(50).mean(); tr = np.where((k.c > m) & (m > m.shift(5)), 1, np.where((k.c < m) & (m < m.shift(5)), -1, 0))
    day0 = (d.t // 864e5) * 864e5; idx = np.searchsorted(k.t.to_numpy(), day0.to_numpy(), side="left") - 1
    return np.where(idx >= 0, tr[np.clip(idx, 0, None)], 0).astype(float)
tot = bad = 0; orig = CB.signals
for sym, stock in (("BTCUSDT", False), ("XAUUSDT", False), ("AMDUSDT", True)):
    d = bars(sym, stock); L = 7 if stock else 24
    I = IB.indicators(d, L); LS, SS = IB.make_signals("综合分翻多/翻空(≥2项净多)", I, day_trend(sym, d, stock))
    for side, key in ((1, "l"), (-1, "s")):
        for kind in ("brk", "tech"):
            if kind == "brk":
                CB.signals = lambda df, L_, e, _s=side: tuple((x & False if i == (1 if _s == 1 else 0) else x) for i, x in enumerate(orig(df, L_, e)))   # 只留一个方向
            else:
                CB.signals = lambda df, L_, e, _s=side: ((LS if _s == 1 else LS & False), (SS if _s == -1 else SS & False)) + orig(df, L_, "breakout")[2:]
            T = CB.simulate(d, L, "F", entry="breakout", max_hold_days=10, bars_per_day=L); CB.signals = orig
            py = [(int(pd.Timestamp(a).timestamp() * 1000), round(e, 4), int(pd.Timestamp(x).timestamp() * 1000)) for a, e, x in zip(T.ts, T.entry, T.exit_ts)] if len(T) else []
            js = [(int(x["t"]), round(x["E"], 4), x["end"]) for x in JS[sym[:3] + key + ("_tech" if kind == "tech" else "")]]
            n = min(len(py), len(js)); same_entry = len(py) == len(js) and all(py[i][:2] == js[i][:2] for i in range(n))
            same_exit = all(js[i][2] is None or py[i][2] == js[i][2] for i in range(n))
            tot += 1; bad += not (same_entry and same_exit)
            print(sym, "做多" if side == 1 else "做空", "突破" if kind == "brk" else "技术面", f"回测 {len(py)} 笔 / 页面 {len(js)} 笔", "进场一致" if same_entry else "进场不一致", "离场一致" if same_exit else "离场不一致")
            if not (same_entry and same_exit): print("   py", py[-3:], "\n   js", js[-3:])
print("对账：", tot - bad, "/", tot, "组完全一致"); sys.exit(1 if bad else 0)
