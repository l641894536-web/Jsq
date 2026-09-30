"""收益、超额收益、成交占比、滚动分位数等基础序列。

约定：所有“宽表”都是 index=交易日、columns=标的代码 的 DataFrame；
所有“过去”指标在 t 日只用到 t 日及以前的数据；所有 fwd_* 指标只用于事后评估。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Frame = pd.DataFrame | pd.Series


def past_return(close: Frame, n: int) -> Frame:
    """t-n 收盘到 t 收盘的收益。"""
    return close / close.shift(n) - 1


def fwd_return(close: Frame, h: int, lag: int = 0) -> Frame:
    """t+lag 收盘入场、持有 h 日的收益（只用于事后评估）。"""
    return close.shift(-(lag + h)) / close.shift(-lag) - 1


def fwd_min_return(close: Frame, h: int, lag: int = 0) -> Frame:
    """入场后 h 日内最低收盘相对入场价的收益（≤0 即持有期最大浮亏）。"""
    future_min = close.rolling(h, min_periods=h).min().shift(-(h + lag))
    return (future_min / close.shift(-lag) - 1).clip(upper=0.0)


def fwd_max(series: Frame, h: int, lag: int = 0) -> Frame:
    """t+lag 之后 h 日内（不含入场日）的最大值。"""
    return series.rolling(h, min_periods=h).max().shift(-(h + lag))


def daily_return(close: Frame) -> Frame:
    return close.pct_change(fill_method=None)


def excess(sector: Frame, market: pd.Series) -> Frame:
    """简单超额：行业收益 − 市场收益（按日期对齐）。"""
    if isinstance(sector, pd.DataFrame):
        return sector.sub(market, axis=0)
    return sector - market


def rank_desc(frame: pd.DataFrame) -> pd.DataFrame:
    """每日横截面排名，1 = 最强。"""
    return frame.rank(axis=1, ascending=False, method="min")


def rolling_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """当前值在过去 window 个值（含当日）中的分位数，只用历史数据，无前视。"""

    def _pct(a: np.ndarray) -> float:
        last = a[-1]
        a = a[~np.isnan(a)]
        if len(a) == 0 or np.isnan(last):
            return np.nan
        return float(np.mean(a <= last))

    return series.rolling(window, min_periods=min_periods).apply(_pct, raw=True)


def rolling_percentile_frame(frame: pd.DataFrame, window: int, min_periods: int) -> pd.DataFrame:
    return frame.apply(lambda s: rolling_percentile(s, window, min_periods))


def expanding_percentile(series: pd.Series, min_periods: int) -> pd.Series:
    """扩展窗口分位数（从样本开始到 t 日）。"""
    return rolling_percentile(series, window=len(series) + 1, min_periods=min_periods)


def rolling_zscore(series: Frame, window: int, min_periods: int | None = None) -> Frame:
    mp = min_periods or window // 2
    mean = series.rolling(window, min_periods=mp).mean()
    std = series.rolling(window, min_periods=mp).std()
    return (series - mean) / std


def index_from_returns(returns: pd.DataFrame, weights: pd.DataFrame | None = None, base: float = 1000.0) -> pd.Series:
    """由成分日收益合成指数；weights 为 t-1 日可得的权重（函数内部会 shift(1)）。"""
    if weights is None:
        r = returns.mean(axis=1, skipna=True)
    else:
        w = weights.shift(1).reindex_like(returns)
        w = w.where(returns.notna())
        w = w.div(w.sum(axis=1), axis=0)
        r = (returns * w).sum(axis=1, min_count=1)
        r = r.fillna(returns.mean(axis=1, skipna=True))
    r = r.fillna(0.0)
    return base * (1 + r).cumprod()
