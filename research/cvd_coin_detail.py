import sys; sys.path.insert(0, "/home/claude/bt")
from cvd_div_bt import *
C = load.binance("1h", COINS, start="2021-06-01")
coins = {s: g.sort_values("ts").reset_index(drop=True) for s, g in C.groupby("symbol")}
btc = regime(daily_close(coins["BTCUSDT"]))
for N in (24, 72):
    T = []
    for mode in ("cvd", "plain"):
        for sym, df in coins.items():
            for t in sim(df, entries(df, 1, N, 12, 24, mode), 1):
                if t["ts"] < pd.Timestamp("2021-11-01", tz="UTC"): continue
                b = btc.reindex([t["ts"].tz_convert(None).normalize()], method="ffill").iloc[0]
                if b is True or b == 1.0: T.append(dict(t, sym=sym, mode=mode))
    T = pd.DataFrame(T); T["y"] = T.ts.dt.year
    print(f"== N={N} 比特币50日线上方，做多 ==")
    print(T.groupby(["mode", "sym"]).r.agg(["count", "mean"]).round(3).unstack(0).to_string())
    print(T.groupby(["mode", "y"]).r.agg(["count", "mean"]).round(3).unstack(0).to_string())
    # 和现行"突破做多"同时出现的比例：同币同一天
