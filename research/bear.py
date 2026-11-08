"""跌破200日线事件：能不能在跌破后10~20天，提前分辨"长熊"和"短暂恐慌"。

事件：指数先连续20天站在200日线上（牛市状态），然后第一次收盘跌到200日线下方2%以上，记为跌破日 t0。
      之后要重新连续20天站上200日线，才会记录下一次。
决策日：t0 之后第 k 个交易日（k = 0 / 10 / 20），只用当天及以前能看到的数据算特征。
结果：从决策日起 6 个月（126个交易日）的涨跌、期间最大再跌幅度。
"""
import sys, os
sys.path.insert(0, "/home/claude/src/Jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import numpy as np
import pandas as pd

BREAK = 0.02
ARM_DAYS = 20


def frame(index="^NDX"):
    d = load.us_daily([index, "^VIX", "^TNX"])
    px = d[d.ticker == index].set_index("date")["close"]
    vix = d[d.ticker == "^VIX"].set_index("date")["close"].reindex(px.index).ffill()
    tnx = d[d.ticker == "^TNX"].set_index("date")["close"].reindex(px.index).ffill()
    f = pd.DataFrame({"px": px, "vix": vix, "tnx": tnx})
    f["ma200"] = f.px.rolling(200).mean()
    f["ma50"] = f.px.rolling(50).mean()
    f["hi252"] = f.px.rolling(252, min_periods=200).max()
    return f.dropna(subset=["ma200"])


def breaks(f):
    above = (f.px > f.ma200).to_numpy()
    deep = (f.px < f.ma200 * (1 - BREAK)).to_numpy()
    out, run, armed = [], 0, False
    for i in range(len(f)):
        run = run + 1 if above[i] else 0
        if run >= ARM_DAYS:
            armed = True
        if armed and deep[i]:
            out.append(i)
            armed = False
    return out


def features(f, t0, k):
    d = t0 + k
    if d >= len(f):
        return None
    px, ma, vix = f.px.to_numpy(), f.ma200.to_numpy(), f.vix.to_numpy()
    hi_pos = int(np.argmax(px[max(0, t0 - 251):t0 + 1])) + max(0, t0 - 251)
    r = dict(
        t0=f.index[t0].date(), dec=f.index[d].date(), k=k,
        # 周期类
        ma200_slope=ma[d] / ma[d - 20] - 1,                       # 200日线最近20天是在上升还是走平/下降
        dist=px[d] / ma[d] - 1,                                    # 离200日线多远
        below_frac=float(np.mean(px[t0:d + 1] < ma[t0:d + 1])),    # 跌破后有多少天待在线下
        dd52=px[d] / f.hi252.iloc[d] - 1,                          # 离一年高点多远
        days_hi_to_break=t0 - hi_pos,                              # 从高点跌到跌破用了几天（快跌/慢跌）
        ma50_below=float(f.ma50.iloc[d] < ma[d]),                 # 50日线是否已在200日线下方（死叉）
        # 情绪类
        vix=vix[d],
        vix_max=np.nanmax(vix[max(0, t0 - 5):d + 1]),
        vix_fade=vix[d] / np.nanmax(vix[max(0, t0 - 5):d + 1]) - 1,  # 恐慌从高点回落了多少
        vix_pre=vix[max(0, t0 - 40)],                              # 跌破前两个月的恐慌水平
        # 利率
        tnx_chg6m=f.tnx.iloc[d] - f.tnx.iloc[max(0, d - 126)],     # 10年期利率半年变化（百分点）
    )
    # 结果
    for H, name in [(63, "3m"), (126, "6m"), (252, "12m")]:
        if d + H < len(f):
            r[f"fwd{name}"] = px[d + H] / px[d] - 1
            r[f"mdd{name}"] = px[d:d + H + 1].min() / px[d] - 1
        else:
            r[f"fwd{name}"] = np.nan
            r[f"mdd{name}"] = np.nan
    if d + 126 < len(f):
        r["below_next6m"] = float(np.mean(px[d:d + 127] < ma[d:d + 127]))
    else:
        r["below_next6m"] = np.nan
    return r


def episodes(index="^NDX", ks=(0, 10, 20), start="1990-06-01"):
    f = frame(index)
    rows = []
    for t0 in breaks(f):
        if f.index[t0] < pd.Timestamp(start):
            continue
        for k in ks:
            r = features(f, t0, k)
            if r:
                rows.append(dict(index=index, **r))
    return pd.DataFrame(rows), f


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    for idx in ["^NDX", "^GSPC"]:
        e, f = episodes(idx)
        e.to_csv(f"bear_{idx.strip('^')}.csv", index=False)
        e0 = e[e.k == 0]
        print(f"\n===== {idx}: {len(e0)} 次跌破")
        cols = ["t0", "dd52", "days_hi_to_break", "ma200_slope", "vix", "vix_pre", "tnx_chg6m", "fwd6m", "mdd6m", "fwd12m", "below_next6m"]
        print(e0[cols].round(3).to_string(index=False))
