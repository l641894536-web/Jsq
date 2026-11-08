"""合约线 × 市场环境：AMD/MU/DELL 近5年小时线（主样本）+ 另外25只科技股（交叉验证）。
出场：A 现状（固定24h低点止损一直拿）、E 浮盈1R后止损挪到开仓价。按 环境 × 多空 拆分。"""
import sys, os
sys.path.insert(0, "/home/claude/src/Jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np
from contract_bt import simulate
from regime import regimes

MAIN = ["AMD", "MU", "DELL"]
OTHER = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "NFLX", "ADBE", "INTC", "CSCO", "AVGO", "QCOM",
         "TXN", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "ORCL", "CRM", "PYPL", "INTU", "IBM", "NXPI"]
START = "2021-11-01"


def run(symbols, variants=("A", "E"), entries=("breakout", "cross")):
    raw = load.dukascopy([s + "USUSD" for s in symbols], start="2021-07")
    raw["sym"] = raw.symbol.str.replace("USUSD", "", regex=False)
    reg = regimes()
    out = []
    for s, g in raw.groupby("sym"):
        g = g.sort_values("ts").reset_index(drop=True)
        for e in entries:
            for v in variants:
                t = simulate(g, 7, v, entry=e, bars_per_day=7)
                if len(t) == 0: continue
                t = t[pd.to_datetime(t.ts) >= pd.Timestamp(START, tz="UTC")]
                t = t.assign(sym=s, entry_rule=e, variant=v)
                out.append(t)
    t = pd.concat(out, ignore_index=True)
    day = pd.to_datetime(t.ts).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    t["state"] = reg["state"].reindex(day).to_numpy()
    t["bigstate"] = t.state.replace({"熊市·恐慌": "熊市", "熊市·平静": "熊市"})
    t["dir"] = t.side.map({1: "做多", -1: "做空"})
    return t


def cell(g):
    return pd.Series({"笔数": len(g), "胜率": (g.r > 0).mean(), "平均R": g.r.mean(), "总R": g.r.sum(),
                      "去掉最大3笔": g.r.sum() - g.r.nlargest(3).sum()})


if __name__ == "__main__":
    for name, syms in [("主样本 AMD/MU/DELL", MAIN), ("交叉验证 另25只科技股", OTHER)]:
        t = run(syms)
        t.to_csv(f"regime_trades_{'main' if syms is MAIN else 'other'}.csv", index=False)
        print(f"\n################ {name}  （缺状态 {t.state.isna().sum()} 笔）")
        for e in ["breakout", "cross"]:
            for v in ["A", "E"]:
                sub = t[(t.entry_rule == e) & (t.variant == v)]
                tab = sub.groupby(["bigstate", "dir"]).apply(cell, include_groups=False)
                tab["胜率"] = (tab["胜率"] * 100).round(0); tab = tab.round(2)
                print(f"\n--- 进场 {e} | 出场 {v} | 全部 {len(sub)} 笔 总R {sub.r.sum():.1f}")
                print(tab.to_string())
