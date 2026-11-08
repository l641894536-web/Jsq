"""正股线回测：好公司跌到位以后，怎么买。

股票池：2021年初按市值选的美股大型科技股（不是按后来涨得好不好选的，避免幸存者偏差）
        + 中概互联网 BABA/PDD/JD/BIDU（腾讯不在数据库里，用它们做同类参考）。
触发：收盘价较过去一年最高点回撤达到 X（主测试 20%，另测 30%）。
三种买法（同一批触发事件）：
  A 跌到位直接一次买满（触发当天收盘买）
  B 等企稳再买：最低点之后至少10天不再创新低，且收盘站上20日均线，当天收盘买满；一年内没出现信号就不买
  C 先买一半，企稳后再买另一半
评估：从触发日起 6 个月 / 12 个月后的收益（没买的部分算现金，收益0）、买入后还要再扛的最大跌幅。
"""
import sys, os
sys.path.insert(0, "/home/claude/src/Jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import numpy as np
import pandas as pd

TECH_2021 = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "NFLX", "ADBE", "INTC", "CSCO", "AVGO",
             "QCOM", "TXN", "AMD", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "ORCL", "CRM", "PYPL", "INTU",
             "IBM", "DELL", "NXPI"]
CHINA = ["BABA", "PDD", "JD", "BIDU"]
START, LOOK = "2021-11-01", 252


def episodes(px, X, rearm):
    """px: 一只股票的复权收盘价序列。返回触发日的位置列表。"""
    hi = px.rolling(LOOK, min_periods=120).max()
    dd = px / hi - 1
    out, armed = [], True
    for i in range(len(px)):
        if np.isnan(dd.iloc[i]):
            continue
        if armed and dd.iloc[i] <= -X:
            if px.index[i] >= pd.Timestamp(START):   # 只记录窗口内的新触发；窗口开始前已经在深跌中的不算
                out.append(i)
            armed = False
        elif not armed and dd.iloc[i] > -rearm:
            armed = True
    return out, dd


def stabilize_signal(px, ma20, i0, max_wait=252):
    low_val, low_pos = px.iloc[i0], i0
    for k in range(i0, min(i0 + max_wait, len(px))):
        if px.iloc[k] < low_val:
            low_val, low_pos = px.iloc[k], k
        if k - low_pos >= 10 and px.iloc[k] > ma20.iloc[k]:
            return k
    return None


def evaluate(px, i0, kB, H):
    """返回三种买法在触发后 H 个交易日的结果；数据不足 H 天返回 None。"""
    end = i0 + H
    if end >= len(px):
        return None
    p0, pE = px.iloc[i0], px.iloc[end]
    path = px.iloc[i0:end + 1]
    r = {}
    # A
    r["A_ret"] = pE / p0 - 1
    r["A_maxdd"] = path.min() / p0 - 1
    # B
    if kB is not None and kB <= end:
        pB = px.iloc[kB]
        r["B_ret"] = pE / pB - 1
        r["B_maxdd"] = px.iloc[kB:end + 1].min() / pB - 1
        r["B_wait"] = kB - i0
        r["B_vs_A_price"] = pB / p0 - 1
        r["B_in"] = True
    else:
        r["B_ret"], r["B_maxdd"], r["B_wait"], r["B_vs_A_price"], r["B_in"] = 0.0, 0.0, np.nan, np.nan, False
    # C：一半在触发日，一半在企稳信号
    r["C_ret"] = 0.5 * r["A_ret"] + 0.5 * r["B_ret"]
    # C 的最大浮亏：按持仓市值算（没买的一半是现金）
    vals = []
    for k in range(i0, end + 1):
        cost = 0.5
        v = 0.5 * px.iloc[k] / p0
        if r["B_in"] and k >= kB:
            v += 0.5 * px.iloc[k] / px.iloc[kB]
            cost = 1.0
        else:
            v += 0.5   # 现金
            cost = 1.0
        vals.append(v / cost - 1)
    r["C_maxdd"] = min(min(vals), 0)
    r["A_maxdd_of_total"] = r["A_maxdd"]
    return r


def main(X=0.20, rearm=0.10):
    tickers = TECH_2021 + CHINA
    d = load.us_daily(tickers, start="2020-01-01")
    q = load.us_daily("QQQ", start="2019-01-01").set_index("date")["adj_close"]
    bull = (q > q.rolling(200).mean()).shift(1)
    rows, open_eps = [], []
    for t, g in d.groupby("ticker"):
        px = g.set_index("date")["adj_close"].dropna()
        ma20 = px.rolling(20).mean()
        eps, dd = episodes(px, X, rearm)
        for i0 in eps:
            kB = stabilize_signal(px, ma20, i0)
            base = dict(ticker=t, date=px.index[i0].date(), price=round(px.iloc[i0], 2),
                        china=t in CHINA, bull=bool(bull.get(px.index[i0], np.nan)) if not pd.isna(bull.get(px.index[i0], np.nan)) else None)
            r6 = evaluate(px, i0, kB, 126)
            r12 = evaluate(px, i0, kB, 252)
            if r12 is None:
                # 还没满一年的事件：单独列出
                low_since = px.iloc[i0:].min() / px.iloc[i0] - 1
                open_eps.append(dict(base, 至今=round(px.iloc[-1] / px.iloc[i0] - 1, 3), 触发后最低=round(low_since, 3),
                                     企稳信号日=(px.index[kB].date() if kB is not None else "还没出现"),
                                     企稳价相对触发价=(round(px.iloc[kB] / px.iloc[i0] - 1, 3) if kB is not None else None)))
                if r6 is None:
                    continue
            rec = dict(base)
            for k, v in (r6 or {}).items():
                rec["m6_" + k] = v
            for k, v in (r12 or {}).items():
                rec["m12_" + k] = v
            rows.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(open_eps)


def table(df, tag):
    df = df.dropna(subset=["m12_A_ret"])
    if len(df) == 0:
        return None
    out = {}
    for m, name in [("A", "A 跌到位一次买满"), ("B", "B 等企稳再买"), ("C", "C 先买一半企稳再买一半")]:
        out[name] = {
            "事件数": len(df),
            "12个月收益中位数": f"{df[f'm12_{m}_ret'].median():+.0%}",
            "12个月收益平均": f"{df[f'm12_{m}_ret'].mean():+.0%}",
            "12个月后亏钱的比例": f"{(df[f'm12_{m}_ret'] < 0).mean():.0%}",
            "6个月收益中位数": f"{df[f'm6_{m}_ret'].median():+.0%}",
            "买入后再跌幅度中位数": f"{df[f'm12_{m}_maxdd'].median():.0%}",
            "买入后再跌超20%的比例": f"{(df[f'm12_{m}_maxdd'] <= -0.20).mean():.0%}",
        }
    t = pd.DataFrame(out).T
    print(f"\n--- {tag}")
    print(t.to_string())
    b = df[df.m12_B_in]
    print(f"    B 一年内等到企稳信号的比例 {df.m12_B_in.mean():.0%}；平均等 {b.m12_B_wait.mean():.0f} 个交易日；"
          f"企稳买入价比触发价：中位数 {b.m12_B_vs_A_price.median():+.0%}，比触发价更便宜的占 {(b.m12_B_vs_A_price < 0).mean():.0%}")
    return t


if __name__ == "__main__":
    for X, rearm in [(0.20, 0.10), (0.30, 0.15)]:
        df, op = main(X, rearm)
        df.to_csv(f"stock_eps_{int(X*100)}.csv", index=False)
        op.to_csv(f"stock_open_{int(X*100)}.csv", index=False)
        print(f"\n================ 触发条件：较一年高点回撤 {X:.0%}")
        table(df, "全部")
        table(df[df.bull == True], "触发时大盘在牛市（QQQ在200日线上）")
        table(df[df.bull == False], "触发时大盘在熊市（QQQ在200日线下）")
        table(df[df.china], "中概互联网（腾讯同类）")
        g = df[df.ticker == "GOOGL"]
        print("\n谷歌的历次触发：")
        print(g[["date", "price", "bull", "m6_A_ret", "m12_A_ret", "m12_A_maxdd", "m12_B_ret", "m12_B_wait", "m12_B_vs_A_price"]].round(3).to_string())
        print("\n还没满一年的触发（谷歌、中概）：")
        print(op[op.ticker.isin(["GOOGL"] + CHINA)].to_string())
