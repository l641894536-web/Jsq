"""市场环境：周期 = 纳指(QQQ)在200日均线上/下；情绪 = VIX 高于/低于 20。都用前一天收盘，避免偷看。"""
import sys, os
sys.path.insert(0, "/home/claude/src/Jsq")
os.environ["MARKET_DATA"] = "/home/claude/market-data"
from market_data import load
import pandas as pd

NAMES = {("up", "calm"): "牛市·平静", ("up", "fear"): "牛市·恐慌", ("down", "fear"): "熊市·恐慌", ("down", "calm"): "熊市·平静"}
VIX_LINE = 20


def regimes():
    d = load.us_daily(["QQQ", "^VIX"], start="2019-01-01")
    q = d[d.ticker == "QQQ"].set_index("date")["adj_close"]
    v = d[d.ticker == "^VIX"].set_index("date")["close"].reindex(q.index).ffill()
    trend = (q > q.rolling(200).mean()).map({True: "up", False: "down"})
    mood = (v >= VIX_LINE).map({True: "fear", False: "calm"})
    raw = pd.DataFrame({"trend": trend, "mood": mood, "qqq": q, "vix": v, "ma200": q.rolling(200).mean()})
    raw["state_today"] = [NAMES[(a, b)] for a, b in zip(raw.trend, raw.mood)]
    raw["state"] = raw["state_today"].shift(1)          # 交易时只能知道昨天收盘的状态
    return raw


if __name__ == "__main__":
    r = regimes()
    w = r.loc["2021-11-01":]
    print("近5年各状态天数:", w.state.value_counts().to_dict())
    # 各状态连续区间
    seg = (w.state != w.state.shift()).cumsum()
    runs = w.groupby(seg).agg(state=("state", "first"), start=("state", lambda s: s.index[0].date()), end=("state", lambda s: s.index[-1].date()), days=("state", "size"))
    print(runs[runs.days >= 15].to_string())
    print("\n最近10天:"); print(r.tail(10)[["qqq", "ma200", "vix", "state_today"]].round(2).to_string())
