"""铂金、钯金、铜、天然气小时线（Dukascopy 商品 CFD，2020 起）：与金银同一套短线规则（L=24，1R挪保本），
环境 = 自身日线收盘在200日线上/下（交易日，用小时线自己合成日线，和页面用币安日线去掉周末的口径一致）。
先把日线和美国期货（PL=F、HG=F）对一下价位，确认点值换算没错。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
from contract_bt import simulate

SYMS = ["XPTCMDUSD", "XPDCMDUSD", "COPPERCMDUSD", "GASCMDUSD"]
NAME = {"XPTCMDUSD": "铂金", "XPDCMDUSD": "钯金", "COPPERCMDUSD": "铜", "GASCMDUSD": "天然气"}
START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))


def daily(g):
    d = g.assign(day=g.ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize())
    d = d[d.day.dt.dayofweek < 5]
    return d.groupby("day").close.last()


def check(dk):
    fut = load.us_daily(["PL=F", "HG=F"]); fut["date"] = pd.to_datetime(fut.date)
    fut = fut.pivot(index="date", columns="ticker", values="close")
    for s, f in [("XPTCMDUSD", "PL=F"), ("COPPERCMDUSD", "HG=F")]:
        g = dk[dk.symbol == s]
        if g.empty:
            continue
        r = (daily(g) / fut[f]).dropna()
        print(f"{NAME[s]} vs {f}: 中位比值 {r.median():.3f}，5%–95% {r.quantile(.05):.3f}–{r.quantile(.95):.3f}，{len(r)}天")
    for s, g in dk.groupby("symbol"):
        d = daily(g)
        print(f"{NAME[s]}: {g.ts.min():%Y-%m} → {g.ts.max():%Y-%m}，{len(g)}根小时线，日线收盘 {d.min():.3f}–{d.max():.3f}，"
              f"每天约{len(g) / max(len(d), 1):.1f}根")


def run():
    dk = load.dukascopy(SYMS, start="2020-01")
    if dk.empty:
        print("还没有数据"); return None
    check(dk)
    out = []
    for s, g in dk.groupby("symbol"):
        g = g.sort_values("ts").reset_index(drop=True)
        d = daily(g)
        bull = (d > d.rolling(200).mean()).where(d.rolling(200).count() >= 200).shift(1)
        for e in ["breakout", "cross"]:
            for v in ["A", "E"]:
                t = simulate(g, 24, v, entry=e, bars_per_day=23)
                t = t[(pd.to_datetime(t.ts) >= START) & (pd.to_datetime(t.ts) < END)].copy()
                day = pd.to_datetime(t.ts).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
                b = bull.reindex(day, method="ffill").to_numpy()
                t["env"] = np.where(pd.isna(b), None, np.where(b == True, "bull", "bear"))
                out.append(t.assign(sym=s, entry_rule=e, variant=v))
    t = pd.concat(out, ignore_index=True)
    t = t[t.env.notna()]
    t.to_csv("commod_trades.csv", index=False)
    t["dir"] = t.side.map({1: "long", -1: "short"})
    t["half"] = np.where(pd.to_datetime(t.ts, utc=True) < MID, "前半", "后半")
    for e in ["breakout", "cross"]:
        for v in ["A", "E"]:
            s = t[(t.entry_rule == e) & (t.variant == v)]
            tab = s.groupby(["sym", "env", "dir"]).r.agg(笔数="size", 胜率=lambda x: round((x > 0).mean() * 100), 平均R="mean").round(3)
            tab = tab.join(s.groupby(["sym", "env", "dir", "half"]).r.mean().unstack("half").round(3))
            print(f"\n--- 进场 {e} | 出场 {v}\n{tab.to_string()}")
    s = t[(t.entry_rule == "breakout") & (t.variant == "E")]
    print("\n--- 四个品种合起来 breakout|E")
    print(s.groupby(["env", "dir"]).r.agg(笔数="size", 平均R="mean").join(
        s.groupby(["env", "dir", "half"]).r.mean().unstack("half")).round(3).to_string())
    return t


if __name__ == "__main__":
    run()
