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
tot = bad = 0; orig = CB.signals
for sym, stock in (("BTCUSDT", False), ("XAUUSDT", False), ("AMDUSDT", True)):
    d = bars(sym, stock); L = 7 if stock else 24
    for side, key in ((1, "l"), (-1, "s")):
        CB.signals = lambda df, L_, e, _s=side: tuple((x & False if i == (1 if _s == 1 else 0) else x) for i, x in enumerate(orig(df, L_, e)))   # 只留一个方向
        T = CB.simulate(d, L, "F", entry="breakout", max_hold_days=10, bars_per_day=L); CB.signals = orig
        py = [(int(pd.Timestamp(a).timestamp() * 1000), round(e, 4), int(pd.Timestamp(x).timestamp() * 1000)) for a, e, x in zip(T.ts, T.entry, T.exit_ts)] if len(T) else []
        js = [(int(x["t"]), round(x["E"], 4), x["end"]) for x in JS[sym[:3] + key]]
        n = min(len(py), len(js)); same_entry = len(py) == len(js) and all(py[i][:2] == js[i][:2] for i in range(n))
        same_exit = all(js[i][2] is None or py[i][2] == js[i][2] for i in range(n))
        tot += 1; bad += not (same_entry and same_exit)
        print(sym, "做多" if side == 1 else "做空", f"回测 {len(py)} 笔 / 页面 {len(js)} 笔", "进场一致" if same_entry else "进场不一致", "离场一致" if same_exit else "离场不一致")
        if not (same_entry and same_exit): print("   py", py[-3:], "\n   js", js[-3:])
print("对账：", tot - bad, "/", tot, "组完全一致"); sys.exit(1 if bad else 0)
