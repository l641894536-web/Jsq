"""新品种短线规则回测：加密（币安1h，比特币200日线定牛熊）、非科技美股（Dukascopy 1h，标普200日线定牛熊）。
规则与金银/科技股完全相同：突破前 L 根K线高点(低点)进场、L 根低点(高点)止损、A=死拿 / E=浮盈1R挪保本，来回成本0.1%。
窗口 2021-11 → 2026-10（近5年），再拆前后两半看稳不稳。"""
import sys, os, json
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
from market_data.config import DK_STOCKS_1H_OTHER
import pandas as pd, numpy as np
from contract_bt import simulate

START = pd.Timestamp("2021-11-01", tz="UTC")
MID = pd.Timestamp("2024-05-01", tz="UTC")
END = pd.Timestamp("2026-11-01", tz="UTC")
CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]


def bull_series(close):
    """收盘在200日均线上 = 牛；用前一天的状态（当天开单时只知道昨天收盘）。"""
    return (close > close.rolling(200).mean()).where(close.rolling(200).count() >= 200).shift(1)


def tag(t, bull, tz):
    day = pd.to_datetime(t.ts)
    day = (day.dt.tz_convert(tz) if tz else day.dt.tz_convert("UTC")).dt.tz_localize(None).dt.normalize()
    b = bull.reindex(day, method="ffill").to_numpy()
    t = t.assign(env=np.where(pd.isna(b), None, np.where(b == True, "bull", "bear")))
    t["dir"] = t.side.map({1: "long", -1: "short"})
    t["half"] = np.where(pd.to_datetime(t.ts) < MID, "前半", "后半")
    return t[t.env.notna()]


def crypto():
    raw = load.binance("1h", CRYPTO)
    btc = raw[raw.symbol == "BTCUSDT"].copy()
    btc["day"] = pd.to_datetime(btc.ts).dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    dclose = btc.groupby("day").close.last()          # 加密 7×24，按日历日
    bull = bull_series(dclose)
    out = []
    for s, g in raw.groupby("symbol"):
        g = g.sort_values("ts").reset_index(drop=True)
        g = g[pd.to_datetime(g.ts) >= pd.Timestamp("2021-08-01", tz="UTC")].reset_index(drop=True)
        for e in ["breakout", "cross"]:
            for v in ["A", "E"]:
                t = simulate(g, 24, v, entry=e, bars_per_day=24)
                t = t[(pd.to_datetime(t.ts) >= START) & (pd.to_datetime(t.ts) < END)]
                out.append(tag(t.assign(sym=s, entry_rule=e, variant=v), bull, None))
    return pd.concat(out, ignore_index=True)


def nontech():
    spx = load.us_daily(["^GSPC", "QQQ"])
    spx["date"] = pd.to_datetime(spx.date)
    px = spx.pivot(index="date", columns="ticker", values="close")
    bull_spx, bull_qqq = bull_series(px["^GSPC"].dropna()), bull_series(px["QQQ"].dropna())
    raw = load.dukascopy([s + "USUSD" for s in DK_STOCKS_1H_OTHER], start="2021-07")
    raw["sym"] = raw.symbol.str.replace("USUSD", "", regex=False)
    out = []
    for s, g in raw.groupby("sym"):
        g = g.sort_values("ts").reset_index(drop=True)
        for e in ["breakout", "cross"]:
            for v in ["A", "E"]:
                t = simulate(g, 7, v, entry=e, bars_per_day=7)
                if len(t) == 0:
                    continue
                t = t[(pd.to_datetime(t.ts) >= START) & (pd.to_datetime(t.ts) < END)]
                t = tag(t.assign(sym=s, entry_rule=e, variant=v), bull_spx, "America/New_York")
                q = tag(t[["ts"]].assign(side=1), bull_qqq, "America/New_York").env
                t["env_qqq"] = q.reindex(t.index).to_numpy()
                out.append(t)
    return pd.concat(out, ignore_index=True)


def stats(t):
    """与 env_static.json contract_stats 同格式：键 'entry|variant|env|dir'。"""
    d = {}
    for (e, v, env, di), g in t.groupby(["entry_rule", "variant", "env", "dir"]):
        w, l = g.r[g.r > 0], g.r[g.r <= 0]
        reach = g.mfe >= 1
        d[f"{e}|{v}|{env}|{di}"] = dict(
            n=int(len(g)), win=round(float((g.r > 0).mean()), 3), avg=round(float(g.r.mean()), 3),
            avg_win=round(float(w.mean()), 2) if len(w) else 0.0, avg_loss=round(float(l.mean()), 2) if len(l) else 0.0,
            p2l=round(float(((g.r_gross < 0) & reach).sum() / max(reach.sum(), 1)), 3))
    return d


def show(t, title, extra=None):
    print(f"\n################ {title}")
    for e in ["breakout", "cross"]:
        for v in ["A", "E"]:
            s = t[(t.entry_rule == e) & (t.variant == v)]
            tab = s.groupby(["env", "dir"]).r.agg(笔数="size", 胜率=lambda x: round((x > 0).mean() * 100),
                                                平均R="mean", 总R="sum").round(3)
            h = s.groupby(["env", "dir", "half"]).r.mean().unstack("half").round(3)
            tab = tab.join(h)
            # 去掉每格最大3笔后的平均（看是不是靠几笔大单）
            tab["去最大3笔平均"] = s.groupby(["env", "dir"]).r.apply(
                lambda x: (x.sum() - x.nlargest(3).sum()) / max(len(x) - 3, 1)).round(3)
            # 多少个品种平均为正
            per = s.groupby(["env", "dir", "sym"]).r.mean().gt(0).groupby(["env", "dir"]).agg(["sum", "size"])
            tab["品种为正"] = per["sum"].astype(str) + "/" + per["size"].astype(str)
            print(f"\n--- 进场 {e} | 出场 {v} | {len(s)} 笔")
            print(tab.to_string())
    if extra is not None:
        extra(t)


def qqq_check(t):
    s = t[(t.entry_rule == "breakout") & (t.variant == "E")]
    print("\n--- 非科技股：换成纳指(QQQ)200日线定牛熊，breakout|E")
    print(s.groupby(["env_qqq", "dir"]).r.agg(笔数="size", 平均R="mean").round(3).to_string())


if __name__ == "__main__":
    c = crypto(); c.to_csv("crypto_trades.csv", index=False)
    show(c, "加密 6 币 · 比特币200日线定牛熊 · 2021-11→2026-10")
    s = c[(c.entry_rule == "breakout") & (c.variant == "E")]
    print("\n--- 加密 breakout|E 分币种 平均R")
    print(s.groupby(["sym", "env", "dir"]).r.mean().unstack(["env", "dir"]).round(3).to_string())
    n = nontech(); n.to_csv("nontech_trades.csv", index=False)
    show(n, f"非科技美股 {n.sym.nunique()} 只 · 标普200日线定牛熊 · 2021-11→2026-10", qqq_check)
    s = n[(n.entry_rule == "breakout") & (n.variant == "E")]
    print("\n--- 非科技 breakout|E 分股票 平均R（牛·多）")
    print(s[(s.env == "bull") & (s.dir == "long")].groupby("sym").r.agg(["size", "mean"]).round(3).T.to_string())
    json.dump({"crypto": stats(c), "stock_nontech": stats(n)}, open("contract_stats_new.json", "w"), ensure_ascii=False)
    print("\nwrote contract_stats_new.json")
