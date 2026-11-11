"""黄金白银的牛熊线从200日线换成50日线（用户 2026-11-11 同意）：把 contract_stats 里 XAUUSD / XAGUSD 的成绩按50日线重新分牛熊。
来源：exit_trades.csv（1小时突破，出场A..J，2021-11~2026-10）和 indicator_trades.csv.gz（各指标翻多翻空）。
牛熊 = COMEX期货（GC=F / SI=F）收盘在自身50日均线上方，用前一天（纽约日期），和 exit_bt.py 的200日线口径一致。
写回 /home/claude/site/env_static.json（原200日线版本另存为 XAUUSD200 / XAGUSD200）。用法：python3 metals50_stats.py [--apply]"""
import sys, json
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
from market_data import load
from build_contract_stats import stats

MID = pd.Timestamp("2024-05-01", tz="UTC")
FUT = {"XAUUSD": "GC=F", "XAGUSD": "SI=F"}
GRP = {"XAUUSD": "黄金", "XAGUSD": "白银"}
IND = {"均线金叉/死叉": "ma", "MACD金叉/死叉": "macd", "RSI超卖反弹/超买回落": "rsi30", "RSI转强/转弱(过55/破45)": "rsi", "突破24小时高/低点": "brk", "综合分翻多/翻空(≥2项净多)": "tech"}


def bull50(tk):
    c = load.us_daily([tk], start="2019-01-01").set_index("date").close.sort_index().dropna()
    return (c > c.rolling(50).mean()).astype(float).where(c.rolling(50).count() >= 50).shift(1)


def tag(t, b):
    day = pd.to_datetime(t.ts, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    v = b.reindex(day, method="ffill").to_numpy()
    t = t.copy(); t["env"] = np.where(pd.isna(v), None, np.where(v == 1, "bull", "bear"))
    return t[t.env.notna()]


X = pd.read_csv("exit_trades.csv"); I = pd.read_csv("indicator_trades.csv.gz")
site = "/home/claude/site/env_static.json"; S = json.load(open(site, encoding="utf8")); CS = S["contract_stats"]
out = {}
for sym, tk in FUT.items():
    b = bull50(tk)
    t = tag(X[X.grp == GRP[sym]], b)
    t["entry_rule"] = "breakout"; t["variant"] = t.v; t["h"] = np.where(pd.to_datetime(t.ts, utc=True) < MID, "h1", "h2")
    d = stats(t)
    for (env, di), g in t.groupby(["env", "dir"]):
        d[f"u|{env}|{di}"] = {v: {"u": round(float((x.r * x.R_pct * 500).mean()), 1), "stop": round(float(x.R_pct.mean() * 100), 1), "n": int(len(x))} for v, x in g.groupby("v")}
    it = tag(I[I.grp == GRP[sym]], b)
    for (env, di), g in it.groupby(["env", "dir"]):
        d[f"ind|{env}|{di}"] = {IND[s]: {"n": int(len(x)), "u": round(float(x.u.mean()), 1), "h1": round(float(x[x.half == "h1"].u.mean()), 1),
                                          "h2": round(float(x[x.half == "h2"].u.mean()), 1), "win": int(round((x.u > 0).mean() * 100))} for s, x in g.groupby("sig") if s in IND}
    out[sym] = d
    for k in ("breakout|E|bull|long", "breakout|E|bull|short", "breakout|E|bear|long", "breakout|E|bear|short"):
        s0, s1 = CS[sym].get(k, {}), d.get(k, {})
        print(sym, k, "200日线:", (s0.get("n"), s0.get("avg"), s0.get("h1"), s0.get("h2")), "→ 50日线:", (s1.get("n"), s1.get("avg"), s1.get("h1"), s1.get("h2")))
    print(sym, "u|bull|long F:", CS[sym]["u|bull|long"]["F"], "→", d["u|bull|long"]["F"], "| u|bear|short F:", CS[sym]["u|bear|short"]["F"], "→", d.get("u|bear|short", {}).get("F"))
if "--apply" in sys.argv:
    for sym, d in out.items():
        if sym + "200" not in CS: CS[sym + "200"] = CS[sym]
        CS[sym] = d
    json.dump(S, open(site, "w", encoding="utf8"), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    print("written")
