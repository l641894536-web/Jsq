"""把所有合约回测的逐笔结果汇总成 env_static.json 里的 contract_stats（同一格式，多了前后两半的平均 h1/h2）。
样本：stock_main=AMD/MU/DELL，stock_other=25只大型科技股（纳指定牛熊），stock_nontech=23只非科技蓝筹（标普定牛熊），
XAUUSD/XAGUSD（自身期货200日线），crypto=6个主流币（比特币200日线），以及有数据的其他大宗（自身200日线）。"""
import json, sys
import pandas as pd, numpy as np

MID = pd.Timestamp("2024-05-01", tz="UTC")


def norm(t, env):
    t = t.copy()
    t["env"] = env
    t["dir"] = t.side.map({1: "long", -1: "short"})
    t["h"] = np.where(pd.to_datetime(t.ts, utc=True) < MID, "h1", "h2")
    return t[t.env.notna()]


def stats(t):
    d = {}
    for (e, v, env, di), g in t.groupby(["entry_rule", "variant", "env", "dir"]):
        w, l = g.r[g.r > 0], g.r[g.r <= 0]
        reach = g.mfe >= 1
        hm = g.groupby("h").r.mean()
        d[f"{e}|{v}|{env}|{di}"] = dict(
            n=int(len(g)), win=round(float((g.r > 0).mean()), 3), avg=round(float(g.r.mean()), 3),
            avg_win=round(float(w.mean()), 2) if len(w) else 0.0, avg_loss=round(float(l.mean()), 2) if len(l) else 0.0,
            p2l=round(float(((g.r_gross < 0) & reach).sum() / max(reach.sum(), 1)), 3),
            h1=round(float(hm.get("h1", np.nan)), 3), h2=round(float(hm.get("h2", np.nan)), 3))
    return d


def bigstate_env(t):
    s = t.bigstate.astype("string")
    return np.where(s.isna(), None, np.where(s.str.startswith("牛"), "bull", "bear"))


def main():
    out = {}
    for key, f in [("stock_main", "regime_trades_main.csv"), ("stock_other", "regime_trades_other.csv")]:
        t = pd.read_csv(f)
        out[key] = stats(norm(t, bigstate_env(t)))
    g = pd.read_csv("gold_trades.csv")
    for sym in ["XAUUSD", "XAGUSD"]:
        x = g[g.sym == sym]
        b = x.bull.astype("string")
        out[sym] = stats(norm(x, np.where(b.isna(), None, np.where(b == "True", "bull", "bear"))))
    c = pd.read_csv("crypto_trades.csv"); out["crypto"] = stats(norm(c, c.env.where(c.env.notna(), None)))
    n = pd.read_csv("nontech_trades.csv"); out["stock_nontech"] = stats(norm(n, n.env.where(n.env.notna(), None)))
    try:
        m = pd.read_csv("commod_trades.csv")
        for sym, x in m.groupby("sym"):
            out[sym] = stats(norm(x, x.env.where(x.env.notna(), None)))
    except FileNotFoundError:
        pass
    return out


if __name__ == "__main__":
    new = main()
    old = json.load(open("contract_stats.json"))
    bad = 0
    for k, v in old.items():
        for kk, s in v.items():
            ns = new[k].get(kk)
            if not ns or ns["n"] != s["n"] or abs(ns["avg"] - s["avg"]) > 0.002:
                bad += 1; print("MISMATCH", k, kk, s, ns)
    print("checked old keys, mismatches:", bad)
    json.dump(new, open("contract_stats_all.json", "w"), ensure_ascii=False)
    for k, v in new.items():
        print(k, {kk.split("|", 2)[2]: (s["n"], s["avg"], s["h1"], s["h2"]) for kk, s in v.items() if kk.startswith("breakout|E")})
    sys.exit(1 if bad else 0)
