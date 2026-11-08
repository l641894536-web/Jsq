"""黄金白银的"大方向"研究。
第1部分（日线，2001–2026）：几个事先定好的环境变量 → 之后20个交易日的涨跌、上涨概率；前后两段分别看。
  金价趋势：收盘在200日线上/下
  美元：美元指数在200日线上/下
  利率：10年期美债收益率60天变化 >0 / ≤0
  波动：20日波动率在过去一年里的分位 高(>0.7)/中/低(<0.3)
  金银比（只看白银）：在过去3年里的分位 高(>0.7)=白银相对便宜 / 低(<0.3)
第2部分（小时线，2021-11 → 2026-10，Dukascopy 现货金银）：和股票合约同一套短线规则
  （突破24h高低点 / 均线金叉 进场，24h低点止损，A 固定止损 / E 1R后保本），按金价趋势×多空拆分。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import numpy as np, pandas as pd
from contract_bt import simulate

pd.set_option("display.width", 250)
d = load.us_daily(["GC=F", "SI=F", "DX-Y.NYB", "^TNX"])
px = d.pivot(index="date", columns="ticker", values="close").sort_index().ffill()
px = px.loc["2000-09-01":]


def states(m):  # m = 'GC=F' or 'SI=F'
    p = px[m]
    f = pd.DataFrame(index=px.index)
    f["trend"] = np.where(p > p.rolling(200).mean(), "金价/银价在200日线上", "金价/银价在200日线下")
    dx = px["DX-Y.NYB"]
    f["usd"] = np.where(dx > dx.rolling(200).mean(), "美元强(200日线上)", "美元弱(200日线下)")
    f["rate"] = np.where(px["^TNX"].diff(60) > 0, "利率60天上升", "利率60天下降")
    vol = p.pct_change().rolling(20).std()
    vr = vol.rolling(250, min_periods=200).apply(lambda a: (a[-1] > a[:-1]).mean(), raw=True)
    f["vol"] = pd.cut(vr, [-0.01, 0.3, 0.7, 1.01], labels=["波动低", "波动中", "波动高"]).astype(str)
    gsr = px["GC=F"] / px["SI=F"]
    gr = gsr.rolling(750, min_periods=500).apply(lambda a: (a[-1] > a[:-1]).mean(), raw=True)
    f["gsr"] = pd.cut(gr, [-0.01, 0.3, 0.7, 1.01], labels=["金银比低", "金银比中", "金银比高(白银相对便宜)"]).astype(str)
    f = f.shift(1)                                    # 只用前一天收盘能知道的状态
    f["fwd20"] = p.shift(-20) / p - 1
    f["half"] = np.where(f.index < "2014-01-01", "2001-13", "2014-26")
    f["recent"] = f.index >= "2021-11-01"
    return f.loc["2001-09-01":].dropna(subset=["fwd20"])


def part1():
    out = {}
    for m, name in [("GC=F", "黄金"), ("SI=F", "白银")]:
        f = states(m)
        base = f.fwd20.mean()
        print(f"\n######## {name}（日线 2001–2026）：之后20个交易日平均 {base:+.2%}，上涨概率 {(f.fwd20 > 0).mean():.0%}")
        for var in ["trend", "usd", "rate", "vol"] + (["gsr"] if m == "SI=F" else []):
            g = f.groupby(var).fwd20
            t = pd.DataFrame({"天数": g.size(), "20天平均": g.mean(), "上涨概率": g.apply(lambda s: (s > 0).mean())})
            for h, x in f.groupby("half"):
                t[h] = x.groupby(var).fwd20.mean()
            t["近5年"] = f[f.recent].groupby(var).fwd20.mean()
            print(t.map(lambda v: f"{v:+.2%}" if isinstance(v, float) and abs(v) < 1 and not isinstance(v, bool) else v).to_string())
        # 趋势 × 美元 组合
        f["combo"] = f.trend.str[-4:] + "·" + f.usd.str[:3]
        g = f.groupby("combo").fwd20
        t = pd.DataFrame({"天数": g.size(), "20天平均": g.mean(), "上涨概率": g.apply(lambda s: (s > 0).mean())})
        for h, x in f.groupby("half"):
            t[h] = x.groupby("combo").fwd20.mean()
        t["近5年"] = f[f.recent].groupby("combo").fwd20.mean()
        print(t.map(lambda v: f"{v:+.2%}" if isinstance(v, float) and abs(v) < 1 else v).to_string())
        out[m] = f
    return out


def part2():
    dk = load.dukascopy(["XAUUSD", "XAGUSD"], start="2021-07")
    rows = []
    for sym, g in dk.groupby("symbol"):
        g = g.sort_values("ts").reset_index(drop=True)
        m = "GC=F" if sym == "XAUUSD" else "SI=F"
        p = px[m]; tr = (p > p.rolling(200).mean()).shift(1)
        for e in ["breakout", "cross"]:
            for v in ["A", "E"]:
                t = simulate(g, 24, v, entry=e, bars_per_day=24)    # 金银现货近乎24小时交易
                t = t[pd.to_datetime(t.ts) >= pd.Timestamp("2021-11-01", tz="UTC")]
                day = pd.to_datetime(t.ts).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
                t = t.assign(sym=sym, entry_rule=e, variant=v, bull=tr.reindex(day, method="ffill").to_numpy())
                rows.append(t)
    t = pd.concat(rows, ignore_index=True)
    t.to_csv("gold_trades.csv", index=False)
    t["环境"] = np.where(t.bull == True, "牛(200日线上)", "熊(200日线下)")
    t["方向"] = t.side.map({1: "做多", -1: "做空"})
    print("\n######## 金银小时线短线规则（2021-11 → 2026-10），按金价/银价大趋势 × 多空")
    agg = t.groupby(["sym", "entry_rule", "variant", "环境", "方向"]).r.agg(笔数="size", 平均R="mean", 总R="sum").round(2)
    print(agg.unstack(["环境", "方向"]).to_string())
    return t


if __name__ == "__main__":
    part1()
    part2()
