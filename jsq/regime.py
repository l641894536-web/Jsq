"""行情状态（只用当时以前的数据，按各标的自己的历史分位自适应）。

趋势强度：考夫曼效率比 ER = |N 小时净涨跌| / N 小时内每根涨跌绝对值之和，越接近 1 越是单边
波动水平：24 小时已实现波动
两者各自与过去 90 天比较取分位，> 0.5 记为“趋势 / 高波动”。组合成 4 种状态：
  趋势·高波动  趋势·低波动  震荡·高波动  震荡·低波动
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import bars

REGIMES = ["趋势·高波", "趋势·低波", "震荡·高波", "震荡·低波"]
FILTERS = {
    "all": None,
    "trend": ["趋势·高波", "趋势·低波"],
    "range": ["震荡·高波", "震荡·低波"],
    "highvol": ["趋势·高波", "震荡·高波"],
    "lowvol": ["趋势·低波", "震荡·低波"],
}
FILTER_CN = {"all": "全部行情", "trend": "只做趋势市", "range": "只做震荡市", "highvol": "只做高波动", "lowvol": "只做低波动"}


def efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    net = (close - close.shift(n)).abs()
    path = close.diff().abs().rolling(n).sum()
    return net / path.replace(0, np.nan)


def regimes(df: pd.DataFrame, er_hours: int = 72, vol_hours: int = 24, lookback_days: int = 90) -> pd.Series:
    c = df["close"]
    er = efficiency_ratio(c, bars(df, er_hours))
    vol = np.log(c).diff().rolling(bars(df, vol_hours)).std()
    lb = bars(df, lookback_days * 24)
    mp = lb // 4
    er_p = er.rolling(lb, min_periods=mp).rank(pct=True)
    vol_p = vol.rolling(lb, min_periods=mp).rank(pct=True)
    trend = np.where(er_p > 0.5, "趋势", "震荡")
    hv = np.where(vol_p > 0.5, "高波", "低波")
    lab = pd.Series([f"{a}·{b}" for a, b in zip(trend, hv)], index=df.index)
    return lab.where(er_p.notna() & vol_p.notna())
