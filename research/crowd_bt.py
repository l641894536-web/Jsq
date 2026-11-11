"""多头/空头"太挤"的指标能不能用来做空/做多（7个主流币，4小时和日线，2021-11 起）。
指标（都和这个币自己过去90天比，算分位，不偷看未来）：
  tb    主动买入占比 = 主动买入成交量 / 总成交量（币安K线自带）
  fund  资金费率（多头付给空头的钱；越高说明做多的人越挤）            —— 需要 load.binance_funding
  oi    持仓量24小时变化（持仓量猛增 = 新钱大量加杠杆）               —— 需要 load.binance_metrics
  ls    全部账户多空人数比、大户持仓多空比                             —— 需要 load.binance_metrics
信号（做空 _S / 做多 _L 镜像），两种：
  "挤了就反着做"：指标到过去90天最高5%（做空）/ 最低5%（做多），且出现第一下转弱（收盘跌破前一根最低）才进；
  "挤了还顺着做"（对照）：指标到最高5%且价格创20根新高 → 做多。
大方向 = 比特币50日线（前一天）。止损2倍ATR，出场：回到20均线或8根K线。成本往返0.1%。单位：100U开5倍每次赚亏多少U。
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/jsq"); sys.path.insert(0, "/home/claude/bt")
from market_data import load
import short_range_bt as S

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]
START, COST = pd.Timestamp("2021-11-01"), 0.001
try: FUND = load.binance_funding(COINS)
except Exception: FUND = pd.DataFrame()
try: MET = load.binance_metrics(COINS)
except Exception: MET = pd.DataFrame()
print("funding rows", len(FUND), "metrics rows", len(MET))


def pct_rank(x, n):
    s = pd.Series(x)
    return s.rolling(n, min_periods=n // 2).apply(lambda w: (w[:-1] < w[-1]).mean() if np.isfinite(w[-1]) else np.nan, raw=True).to_numpy()


def bars(raw, rule):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "taker_buy_volume": "sum"}
    d = raw.set_index("ts")[list(agg)].astype(float).resample(rule).agg(agg).dropna(subset=["close"])
    return d


def run_one(sym, tf, raw, big):
    rule, per_day = ("4h", 6) if tf == "4小时" else ("1D", 1)
    d = bars(raw, rule); idx = d.index
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close")); n = len(c)
    ax, atr = S.adx_atr(d.high, d.low, d.close)
    tsn = idx.tz_localize(None)
    bg = big.reindex(tsn.floor("D"), method="ffill").to_numpy()
    ma20 = d.close.rolling(20).mean().to_numpy()
    pl, ph = np.r_[np.nan, l[:-1]], np.r_[np.nan, h[:-1]]
    crackD, crackU = c < pl, c > ph
    hi20 = d.close.rolling(20).max().shift(1).to_numpy(); lo20 = d.close.rolling(20).min().shift(1).to_numpy()
    W = 90 * per_day
    ind = {}
    tb = (d.taker_buy_volume / d.volume.replace(0, np.nan)).to_numpy(); ind["tb"] = pct_rank(tb, W)
    if len(FUND):
        f = FUND[FUND.symbol == sym].set_index("ts").rate.astype(float)
        if len(f) > 50:
            fr = f.reindex(idx.union(f.index)).ffill().reindex(idx).to_numpy()
            ind["fund"] = pct_rank(fr, W); ind["fund_raw"] = fr
    if len(MET):
        m = MET[MET.symbol == sym].set_index("ts")
        if len(m) > 500:
            mm = m[["oi", "ls_acct", "top_ls_pos"]].astype(float).resample(rule).last().reindex(idx)
            oi = mm.oi.to_numpy(); k = per_day if per_day > 1 else 1
            oich = np.log(oi / np.r_[[np.nan] * k, oi[:-k]])
            ind["oi"] = pct_rank(oich, W); ind["ls"] = pct_rank(mm.ls_acct.to_numpy(), W); ind["toppos"] = pct_rank(mm.top_ls_pos.to_numpy(), W)
    rec = lambda x, k=3: S.recent(np.nan_to_num(x.astype(float)) > 0, k)
    sigs = {}
    for nm, p in ind.items():
        if nm == "fund_raw": continue
        hi, lo = p >= 0.95, p <= 0.05
        sigs[f"{nm}_挤多→空"] = (-1, rec(hi) & crackD)
        sigs[f"{nm}_挤空→多"] = (1, rec(lo) & crackU)
        sigs[f"{nm}_挤多仍追多"] = (1, hi & (c > hi20))
        sigs[f"{nm}_挤空仍追空"] = (-1, lo & (c < lo20))
    if "fund_raw" in ind:
        fr = ind["fund_raw"]
        sigs["fund_负费率→多"] = (1, S.first(np.nan_to_num(fr) < 0) & crackU)
        sigs["fund_费率>0.05%→空"] = (-1, rec(np.nan_to_num(fr) >= 0.0005) & crackD)
    if "oi" in ind and "tb" in ind:
        hot = (ind["oi"] >= 0.9) & (ind["tb"] >= 0.9)
        sigs["oi+tb_猛加杠杆追涨后转弱→空"] = (-1, rec(hot & (c > hi20), 4) & crackD)
    rows = []
    for nm, (side, arr) in sigs.items():
        arr = S.first(np.nan_to_num(arr.astype(float)) > 0); busy = -1
        ex = (lambda j: c[j] <= ma20[j]) if side == -1 else (lambda j: c[j] >= ma20[j])
        if "追" in nm: ex = (lambda j: c[j] < ma20[j]) if side == 1 else (lambda j: c[j] > ma20[j])
        for i in np.flatnonzero(arr):
            if i <= busy or i < 60 or tsn[i] < START or bg[i] != bg[i] or not np.isfinite(atr[i]): continue
            j, px = S.sim(o, h, l, c, i, side, c[i] - side * 2 * atr[i], 8 if "追" not in nm else 15, ex); busy = j
            rows.append((sym[:-4], tf, nm, tsn[i], bool(bg[i]), (side * (px / c[i] - 1) - COST) * 500))
    return rows


btc = S.bars_from(load.binance("1h", "BTCUSDT"), "1D"); b50 = S.above(btc.close, 50)
rows = []
for s in COINS:
    raw = load.binance("1h", s)
    for tf in ("4小时", "日线"): rows += run_one(s, tf, raw, b50)
T = pd.DataFrame(rows, columns=["inst", "tf", "sig", "ts", "big", "u"]); T.to_csv("crowd_trades.csv.gz", index=False)
T["big"] = T.big.map({True: "牛", False: "熊"}); T["fam"] = T.sig.str.split("_").str[0]
mid = pd.Timestamp("2024-05-01")


def summ(g):
    dd = g.groupby("ts").u.mean(); a, b = dd[dd.index < mid], dd[dd.index >= mid]
    return pd.Series({"笔": len(g), "信号日": len(dd), "u": round(g.u.mean(), 2), "胜%": round((g.u > 0).mean() * 100), "前": round(a.mean(), 2) if len(a) else np.nan,
                      "后": round(b.mean(), 2) if len(b) else np.nan, "日1": len(a), "日2": len(b), "t": round(dd.mean() / dd.std() * np.sqrt(len(dd)), 1) if len(dd) > 2 else 0})


pd.set_option("display.width", 220); pd.set_option("display.max_rows", 300)
R = T.groupby(["tf", "big", "sig"]).apply(summ).reset_index(); R.to_csv("crowd_report.csv", index=False)
print(R.sort_values(["tf", "big", "t"], ascending=[True, True, False]).to_string(index=False))
ok = R[(R.信号日 >= 30) & (R.前 > 0) & (R.后 > 0) & (R.t >= 2.5)]
print("\n过关（前后两段都赚、t>=2.5）：", len(ok), "/", len(R)); print(ok.to_string(index=False))
