"""个股信号 × 市场环境（2016–2026，全A剔除ST、上市不满一年的）。
信号1 放量突破：收盘创60日新高，且当天成交额 ≥ 过去20天均值的1.5倍；收盘涨停的剔除（买不进）。看之后20天。
信号2 深跌抄底：收盘价第一次跌到一年最高点的70%以下。看之后60天。
每个信号日先把当天所有信号平均，再对日期平均（避免同一天几百只股票把结果撑大）。"""
import sys; sys.path.insert(0, "/home/claude/bt")
import numpy as np
import pandas as pd
from sentiment import compute

s, g, m = compute()
temp = pd.read_csv("sentiment_temp.csv", index_col=0, parse_dates=True)
dates = g["dates"]
ok, adj, age, traded = m["ok"], m["adj"], m["age"], m["traded"]
close = g["close"].astype("float64")
from sentiment import limits
up, _ = limits(g)
at_limit = np.abs(close - up) < 0.0051

adjf = pd.DataFrame(adj).ffill().to_numpy()            # 停牌期间用最后价格
amt = pd.DataFrame(np.where(traded, g["amount"], np.nan))
amt20 = amt.shift(1).rolling(20, min_periods=15).mean().to_numpy()
A = pd.DataFrame(adj)
hi60_prev = A.shift(1).rolling(60, min_periods=50).max().to_numpy()
hi250 = m["hi250"]
base = ok & (age >= 250)

sig_brk = base & (adj > hi60_prev) & (g["amount"] >= 1.5 * amt20) & ~at_limit
below = adj <= 0.7 * hi250
below_prev = np.vstack([np.zeros((1, below.shape[1]), bool), below[:-1]])
sig_dip = base & below & ~below_prev

ew = s["等权指数"].to_numpy()


def evaluate(sig, H, name):
    rows = []
    T = len(dates)
    for t in range(T - H):
        if dates[t] < pd.Timestamp("2016-01-01"):
            continue
        idx = np.where(sig[t])[0]
        if len(idx) == 0:
            continue
        fwd = adjf[t + H, idx] / adj[t, idx] - 1
        fwd = fwd[np.isfinite(fwd)]
        if len(fwd) == 0:
            continue
        mkt = ew[t + H] / ew[t] - 1
        rows.append(dict(date=dates[t], n=len(fwd), ret=fwd.mean(), win=(fwd > 0).mean(), excess=fwd.mean() - mkt))
    d = pd.DataFrame(rows).set_index("date")
    d = d.join(temp[["温度", "牛熊"]])
    d["情绪"] = pd.cut(d["温度"], [-1, 40, 60, 101], labels=["偏冷(<40)", "中性", "偏热(>60)"])
    d["牛熊"] = d["牛熊"].str[:1]
    d["half"] = np.where(d.index < "2021-01-01", "2016-20", "2021-26")
    d.to_csv(f"sig_{name}.csv")
    return d


def table(d, H, title):
    def f(x):
        return pd.Series({"信号日数": len(x), "信号数": int(x.n.sum()), f"之后{H}天平均": f"{x.ret.mean():+.1%}",
                          "上涨比例": f"{x.win.mean():.0%}", "跑赢全A": f"{x.excess.mean():+.1%}"})
    print(f"\n===== {title}")
    print("全部:", f(d).to_dict())
    print(d.groupby(["牛熊", "情绪"], observed=True).apply(f, include_groups=False).to_string())
    print("前后两半分别（牛熊×情绪 的之后平均）:")
    print(d.groupby(["half", "牛熊", "情绪"], observed=True).ret.mean().unstack("情绪").map(lambda x: f"{x:+.1%}").to_string())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    d1 = evaluate(sig_brk, 20, "breakout")
    table(d1, 20, "信号1 放量突破60日新高 → 之后20天")
    d2 = evaluate(sig_dip, 60, "dip")
    table(d2, 60, "信号2 跌到一年高点的70%以下 → 之后60天")
