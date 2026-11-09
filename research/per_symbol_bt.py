"""每只没进过分组回测的股票合约，用它自己的 Dukascopy 小时线（近5年）单独回测，结果写进 gh-pages env_static.json 的
contract_stats["sym_<代码>"]（格式和分组统计一样，多了 exit|环境|方向 的出场对比）。
规则与结论卡相同：突破前一个交易日（7根时段小时线）高/低点进场、止损在另一端外 0.1%；E=1R保本，F=1R保本+跟踪3天低点，
G=固定2R，B=1R先平一半，J=2R先平一半+跟踪。环境：非科技（和卡片 NONTECH 一致）看标普200日线，其余看纳指。
用法：python3 per_symbol_bt.py [--apply]   （--apply 时写入 /home/claude/site 并推送 gh-pages）"""
import sys, os, json, subprocess
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
from market_data import config as C
import pandas as pd, numpy as np
from contract_bt import simulate
import exit_bt as X
from build_contract_stats import stats as group_stats

ALIAS = {"META": "FB"}                     # Dukascopy 还在用旧代码
NONTECH = {"JPM", "GS", "BAC", "BX", "V", "LLY", "UNH", "ABBV", "MRK", "PFE", "AMGN", "COST", "WMT", "HD", "MCD", "KO", "NKE", "DIS",
           "XOM", "OXY", "CAT", "ACN", "XLE", "SPY", "IBKR", "SOFI", "MRNA", "EQT", "GDX", "IWM", "CEG", "VST", "GEV", "BE"}
TESTED = {"AMD", "MU", "DELL", "AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX",
          "MRVL", "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN", "BA", "BAC", "COST", "CVX", "DIS", "GS", "HD", "JNJ",
          "JPM", "KO", "LLY", "MA", "MCD", "MRK", "NKE", "PEP", "PFE", "PG", "UNH", "V", "WFC", "WMT", "XOM"}


def perps():
    st = json.load(open("/home/claude/market-data/status.json"))["stages"]["binance"].get("stock_perps", [])
    return sorted({p.replace("USDT", "") for p in st} - TESTED)


def main(apply):
    us = load.us_daily(["QQQ", "^GSPC"]); us["date"] = pd.to_datetime(us.date)
    px = us.pivot(index="date", columns="ticker", values="close")
    env_n, env_s = X.bull_daily(px["QQQ"]), X.bull_daily(px["^GSPC"])
    out, note = {}, []
    for tk in perps():
        dk = ALIAS.get(tk, tk) + "USUSD"
        g = load.dukascopy(dk, start="2021-06")
        if g.empty or (g.ts.max() - g.ts.min()).days < 730:
            note.append(f"{tk}: 小时线不够两年（{0 if g.empty else (g.ts.max() - g.ts.min()).days} 天）"); continue
        g = g.sort_values("ts").reset_index(drop=True)
        bull = env_s if tk in NONTECH else env_n
        parts = []
        for v in ["E", "F", "G", "B", "J"]:
            t = X.tagged(simulate(g, 7, v, entry="breakout", bars_per_day=7), bull)
            parts.append(t.assign(v=v, entry_rule="breakout", variant=v))
        T = pd.concat(parts, ignore_index=True)
        T = T.rename(columns={"half": "h"}) if "half" in T else T
        T["h"] = np.where(pd.to_datetime(T.ts, utc=True) < X.MID, "h1", "h2")
        T["env"] = T.env.astype(object)
        s = group_stats(T[T.v == "E"])
        for (e, d), x in T.groupby(["env", "dir"]):
            ex = {}
            for v, y in x.groupby("v"):
                hm = y.groupby("h").r.mean()
                ex[v] = dict(n=int(len(y)), avg=round(float(y.r.mean()), 3), win=int(round((y.r > 0).mean() * 100)),
                             h1=round(float(hm.get("h1", np.nan)), 3), h2=round(float(hm.get("h2", np.nan)), 3))
            s[f"exit|{e}|{d}"] = ex
        s["_meta"] = dict(source=dk, start=str(g.ts.min().date()), env="标普" if tk in NONTECH else "纳指")
        out[f"sym_{tk}"] = s
        b = s.get("breakout|E|bull|long", {})
        note.append(f"{tk}: {s['_meta']['start']} 起，牛市突破做多 {b.get('n', 0)} 笔，平均 {b.get('avg', float('nan')):+.2f} 份（前段 {b.get('h1', float('nan')):+.2f}/后段 {b.get('h2', float('nan')):+.2f}）")
    print("\n".join(note))
    if apply and out:
        subprocess.run("git -C /home/claude/site pull -q --ff-only", shell=True)
        st = json.load(open("/home/claude/site/env_static.json"))
        st["contract_stats"].update(out)
        st["contract_stats_note"]["per_symbol"] = "sym_<代码>：没进分组回测的股票合约用自己的 Dukascopy 小时线单独回测（research/per_symbol_bt.py），每格不到60笔算样本少"
        json.dump(st, open("/home/claude/site/env_static.json", "w"), ensure_ascii=False, indent=1)
        e = json.load(open("/home/claude/site/env.json")); e["contract_stats"] = st["contract_stats"]; e["contract_stats_note"] = st["contract_stats_note"]
        json.dump(e, open("/home/claude/site/env.json", "w"), ensure_ascii=False, separators=(",", ":"))
        msg = f"单只股票合约回测：{', '.join(k[4:] for k in out)}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01FxLYU45ba7o97xL9CtxbkE"
        subprocess.run(["git", "-C", "/home/claude/site", "add", "env_static.json", "env.json"])
        subprocess.run(["git", "-C", "/home/claude/site", "commit", "-q", "-m", msg])
        subprocess.run("git -C /home/claude/site push -q origin gh-pages", shell=True)
        print(f"applied {len(out)} symbols")


if __name__ == "__main__":
    main("--apply" in sys.argv)
