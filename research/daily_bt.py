"""日线级别突破规则（美股）：
  进场：收盘高于前20天最高价 → 第二天开盘做多；收盘低于前20天最低价 → 第二天开盘做空
  止损：开仓价 ∓ 2倍ATR20（1R = 2倍ATR）；变体 E：浮盈到1R后止损挪到开仓价
  离场：收盘跌破前10天最低价（多）/升破前10天最高价（空）→ 第二天开盘走；最长拿120个交易日
  成本：来回0.1%；多单再扣资金费 0.04%/交易日（币安永续常见0.01%/8小时，含周末），空单不扣
  环境：科技/通信/额外成长股看纳指(QQQ) 200日线，其余看标普
  对照组：同样的止损和离场，只是每10个交易日随便进场一次——突破进场要比它好才算真有用（顺带扣掉成分股幸存者偏差）
样本 2021-11 → 2026-10，前后两段 2024-05 分界。"""
import sys, os, json
sys.path.insert(0, "/home/claude/jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd, numpy as np

START, MID, END = pd.Timestamp("2021-11-01"), pd.Timestamp("2024-05-01"), pd.Timestamp("2026-11-01")
COST, FUND = 0.001, 0.0004
TECH_SECTORS = {"Information Technology", "Communication Services"}


def sim(o, h, l, c, atr, i0, side, be, max_hold=120):
    """i0 = 信号日（收盘确认），第 i0+1 天开盘进场。返回 (退出下标, r毛, mfe, 持有天数)。"""
    n = len(c)
    e = i0 + 1
    if e >= n:
        return None
    E0 = o[e]; R = 2 * atr[i0]
    if not np.isfinite(R) or R <= 0:
        return None
    stop = E0 - side * R
    mfe = 0.0
    for d in range(e, min(n, e + max_hold)):
        # 1) 止损（跳空穿过就按开盘价）
        if side == 1 and l[d] <= stop:
            px = min(o[d], stop) if d > e else min(o[d], stop) if o[d] < stop else stop
            return d, (px - E0) / R, mfe, d - e + 1
        if side == -1 and h[d] >= stop:
            px = max(o[d], stop) if o[d] > stop else stop
            return d, (E0 - px) / R, mfe, d - e + 1
        fav = (h[d] - E0) / R if side == 1 else (E0 - l[d]) / R
        mfe = max(mfe, fav)
        if be and mfe >= 1:
            stop = max(stop, E0) if side == 1 else min(stop, E0)
        # 2) 收盘破10日反向极值 → 次日开盘走
        if d >= 10:
            if side == 1 and c[d] < l[d - 10:d].min() and d + 1 < n:
                return d + 1, (o[d + 1] - E0) / R, mfe, d - e + 2
            if side == -1 and c[d] > h[d - 10:d].max() and d + 1 < n:
                return d + 1, (E0 - o[d + 1]) / R, mfe, d - e + 2
    d = min(n, e + max_hold) - 1
    return d, side * (c[d] - E0) / R, mfe, d - e + 1


def run_stock(g, env, sym):
    g = g.reset_index(drop=True)
    o, h, l, c = (g[k].to_numpy(float) for k in ["open", "high", "low", "close"])
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)
    atr = pd.Series(tr).rolling(20).mean().to_numpy()
    hh = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    ll = pd.Series(l).shift(1).rolling(20).min().to_numpy()
    dates = g.date.to_numpy()
    ok = (g.date >= START) & (g.date < END)
    bull = env.reindex(g.date).to_numpy()
    out = []
    for be in (False, True):
        for side in (1, -1):
            busy = -1
            sig = np.where(ok & ((c > hh) if side == 1 else (c < ll)))[0]
            for i in sig:
                if i <= busy or not np.isfinite(bull[i]):
                    continue
                r = sim(o, h, l, c, atr, i, side, be)
                if r is None:
                    continue
                x, rg, mfe, days = r
                busy = x
                E0 = o[i + 1]; R = 2 * atr[i]
                cost = (COST + (FUND * days if side == 1 else 0)) * E0 / R
                out.append((sym, "breakout", "E" if be else "A", side, dates[i], rg, rg - cost, mfe, days, R / E0, bull[i]))
            # 对照：每10个交易日随便进一次（同一套止损离场），不管有没有持仓
            for i in np.where(ok)[0][::10]:
                if not np.isfinite(bull[i]):
                    continue
                r = sim(o, h, l, c, atr, i, side, be)
                if r is None:
                    continue
                x, rg, mfe, days = r
                E0 = o[i + 1]; R = 2 * atr[i]
                cost = (COST + (FUND * days if side == 1 else 0)) * E0 / R
                out.append((sym, "random", "E" if be else "A", side, dates[i], rg, rg - cost, mfe, days, R / E0, bull[i]))
    return out


def main():
    u = pd.read_csv("/home/claude/market-data/us/meta/universe.csv")
    stocks = u[~u.source.isin(["etf", "future", "index"])]
    tech = set(stocks.ticker[stocks.sector.isin(TECH_SECTORS) | stocks.sector.isna()])
    perps = [s[:-4] for s in json.load(open("perp_stocks.json"))]
    tick = sorted(set(stocks.ticker) | (set(perps) & set(u.ticker)))
    d = load.us_daily(tick + ["QQQ", "^GSPC"], start="2020-06-01")
    px = d.pivot(index="date", columns="ticker", values="close")
    env_n = (px["QQQ"] > px["QQQ"].rolling(200).mean()).astype(float).where(px["QQQ"].rolling(200).count() >= 200)
    env_s = (px["^GSPC"] > px["^GSPC"].rolling(200).mean()).astype(float).where(px["^GSPC"].rolling(200).count() >= 200)
    rows = []
    for sym, g in d[d.ticker.isin(tick)].groupby("ticker"):
        g = g.dropna(subset=["open", "high", "low", "close"])
        if len(g) < 300:
            continue
        rows += run_stock(g, env_n if sym in tech else env_s, sym)
    t = pd.DataFrame(rows, columns=["sym", "entry_rule", "variant", "side", "date", "r_gross", "r", "mfe", "days", "R_pct", "bull"])
    t["env"] = np.where(t.bull == 1, "bull", "bear")
    t["dir"] = t.side.map({1: "long", -1: "short"})
    t["half"] = np.where(pd.to_datetime(t.date) < MID, "h1", "h2")
    t["perp"] = t.sym.isin(perps)
    t["grp"] = np.where(t.sym.isin(["AMD", "MU", "DELL"]), "main3", np.where(t.sym.isin(tech), "tech", "nontech"))
    t.to_csv("daily_trades.csv", index=False)
    return t


def report(t):
    def tab(s):
        g = s.groupby(["env", "dir"])
        x = g.r.agg(笔数="size", 胜率=lambda v: round((v > 0).mean() * 100), 平均R="mean")
        x["持有天"] = g.days.median()
        x = x.join(s.groupby(["env", "dir", "half"]).r.mean().unstack("half"))
        x["止损%"] = (g.R_pct.median() * 100).round(1)
        return x.round(3)
    for name, m in [("全部美股", slice(None)), ("币安股票合约那批", t.perp), ("AMD/美光/戴尔", t.grp == "main3")]:
        s = t[m] if not isinstance(m, slice) else t
        print(f"\n################ {name}：{s.sym.nunique()} 只")
        for v in ["A", "E"]:
            b, rnd = tab(s[(s.entry_rule == "breakout") & (s.variant == v)]), tab(s[(s.entry_rule == "random") & (s.variant == v)])
            b["随便进场平均R"] = rnd.平均R
            b["突破多赚"] = (b.平均R - rnd.平均R).round(3)
            print(f"\n--- 出场 {v}（{'浮盈1R挪保本' if v == 'E' else '死拿到离场'}）\n{b.to_string()}")


if __name__ == "__main__":
    t = main() if "--cached" not in sys.argv else pd.read_csv("daily_trades.csv")
    report(t)
