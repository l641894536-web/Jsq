"""哪些股票适合做合约短线（突破做多/跌破做空，1R挪保本）？
用开单前一个交易日收盘就能算出的条件分组，看平均每笔R：
  vol20  近20日日波动（年化）      mom60  近60日涨幅      rs60  60日涨幅减纳指(QQQ)60日涨幅
  hi252  离52周最高点多远          a200   收盘在自身200日线上方   a50  在50日线上方
样本：AMD/美光/戴尔 + 22只科技股 + 23只非科技蓝筹，2021-11 → 2026-10，breakout|E。
前半段 2021-11 → 2024-04 用来找条件（分位数阈值也只用前半段算），后半段 2024-05 → 2026-10 检验。"""
import sys, os
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np

START, MID, END = (pd.Timestamp(x, tz="UTC") for x in ("2021-11-01", "2024-05-01", "2026-11-01"))


def trades():
    m = pd.read_csv("regime_trades_main.csv"); m["grp"] = "main3"
    o = pd.read_csv("regime_trades_other.csv"); o["grp"] = "tech"
    n = pd.read_csv("nontech_trades.csv"); n["grp"] = "nontech"
    t = pd.concat([m, o, n], ignore_index=True)
    t = t[(t.entry_rule == "breakout") & (t.variant == "E")].copy()
    t["ts"] = pd.to_datetime(t.ts, utc=True)
    t = t[(t.ts >= START) & (t.ts < END)]
    t["dir"] = t.side.map({1: "long", -1: "short"})
    t["half"] = np.where(t.ts < MID, "h1", "h2")
    t["day"] = t.ts.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    return t.drop(columns=[c for c in ["state", "bigstate", "env", "env_qqq"] if c in t])


def features(syms):
    d = load.us_daily(list(syms) + ["QQQ", "^GSPC"])
    d["date"] = pd.to_datetime(d.date)
    px = d.pivot(index="date", columns="ticker", values="close").sort_index()
    ret = px.pct_change()
    f = {
        "vol20": ret.rolling(20).std() * np.sqrt(252),
        "mom60": px / px.shift(60) - 1,
        "hi252": px / px.rolling(252).max() - 1,
        "a200": (px > px.rolling(200).mean()).astype(float).where(px.rolling(200).count() >= 200),
        "a50": (px > px.rolling(50).mean()).astype(float).where(px.rolling(50).count() >= 50),
    }
    f["rs60"] = f["mom60"].sub(f["mom60"]["QQQ"], axis=0)
    ndx_bull = (px["QQQ"] > px["QQQ"].rolling(200).mean()).astype(float)
    spx_bull = (px["^GSPC"] > px["^GSPC"].rolling(200).mean()).astype(float)
    # 全部往后挪一天：第 D 天开单只用到 D-1 收盘
    f = {k: v.shift(1) for k, v in f.items()}
    return f, ndx_bull.shift(1), spx_bull.shift(1)


def attach(t, f, ndx, spx):
    for k, v in f.items():
        s = v.stack()
        s.index.names = ["day", "sym"]
        t = t.join(s.rename(k), on=["day", "sym"])
    t["ndx_bull"] = ndx.reindex(t.day).to_numpy()
    t["spx_bull"] = spx.reindex(t.day).to_numpy()
    t["mkt_bull"] = np.where(t.grp == "nontech", t.spx_bull, t.ndx_bull)
    return t


def bucket_table(t, col, q=(0, 1 / 3, 2 / 3, 1)):
    h1 = t[t.half == "h1"]
    edges = h1[col].quantile(list(q)).to_numpy().copy()
    edges[0], edges[-1] = -np.inf, np.inf
    lab = [f"{col}≤{edges[1]:.3g}", f"中间", f"{col}>{edges[2]:.3g}"] if len(q) == 4 else None
    t = t.assign(b=pd.cut(t[col], edges, labels=lab))
    g = t.groupby(["b", "half"], observed=True).r.agg(["size", "mean"]).unstack("half")
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    g["main3占比"] = t.groupby("b", observed=True).grp.apply(lambda x: (x == "main3").mean()).round(2)
    return g.round(3)


if __name__ == "__main__":
    t = trades()
    f, ndx, spx = features(t.sym.unique())
    t = attach(t, f, ndx, spx)
    t.to_csv("feat_trades.csv", index=False)
    print("缺特征的笔数:", t[["vol20", "mom60", "a200"]].isna().any(axis=1).sum(), "/", len(t))
    for di in ["long", "short"]:
        for mb in [1.0, 0.0]:
            s = t[(t.dir == di) & (t.mkt_bull == mb)].dropna(subset=["vol20", "mom60", "hi252", "a200", "rs60"])
            print(f"\n################ {'做多' if di == 'long' else '做空'} · 大盘{'牛' if mb else '熊'} · {len(s)}笔  "
                  f"(h1平均 {s[s.half=='h1'].r.mean():.3f}, h2平均 {s[s.half=='h2'].r.mean():.3f})")
            for col in ["vol20", "mom60", "rs60", "hi252"]:
                print(f"\n-- {col}"); print(bucket_table(s, col).to_string())
            for col in ["a200", "a50"]:
                g = s.groupby([col, "half"]).r.agg(["size", "mean"]).unstack("half").round(3)
                print(f"\n-- {col}"); print(g.to_string())
