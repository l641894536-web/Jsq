"""事件识别与去簇（de-clustering）。

同一轮行情里信号会连续触发很多天，如果每天都算一个样本，
样本数被严重夸大（其实是同一件事）。所以所有事件都要去簇：
- 穿越型：序列从下向上穿越阈值才触发，且必须先回落到 rearm 以下才允许再次触发；
- 最小间隔：同一标的两次事件至少间隔 min_gap 个交易日。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def crossing_events(series: pd.Series, threshold: float, rearm: float | None = None, min_gap: int = 0) -> pd.DatetimeIndex:
    """向上穿越 threshold 的日期（去簇）。rearm 默认等于 threshold。"""
    rearm = threshold if rearm is None else rearm
    x = series.to_numpy(dtype=float)
    armed = False
    last = -10**9
    hits = []
    for i, v in enumerate(x):
        if not np.isfinite(v):
            continue
        if v < rearm:
            armed = True
        if armed and v >= threshold:
            # 首日数据就在阈值之上时不算“穿越”（不知道何时开始的）；
            # 距上次事件不足 min_gap 的穿越视为同一事件的延续
            if i - last >= min_gap:
                hits.append(i)
            last = i
            armed = False
    return series.index[hits]


def condition_events(cond: pd.Series, min_gap: int) -> pd.DatetimeIndex:
    """条件为真的日子里，与上一次事件间隔 ≥ min_gap 的才算新事件。"""
    c = cond.eq(True).to_numpy(dtype=bool)
    last = -10**9
    hits = []
    for i, v in enumerate(c):
        if v and i - last >= min_gap:
            hits.append(i)
            last = i
        elif v:
            last = i  # 连续触发延长同一事件
    return cond.index[hits]


def events_frame(per_key: dict[str, pd.DatetimeIndex], **extra) -> pd.DataFrame:
    rows = [{"date": d, "key": k, **extra} for k, dates in per_key.items() for d in dates]
    df = pd.DataFrame(rows, columns=["date", "key", *extra.keys()])
    return df.sort_values(["date", "key"]).reset_index(drop=True)


def concat_events(frames: list[pd.DataFrame], columns: list[str] | None = None) -> pd.DataFrame:
    """合并多组事件；全空时返回带列名的空表。"""
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=columns or ["date", "key"])
    return pd.concat(frames, ignore_index=True)


def restrict_dates(events: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    m = pd.Series(True, index=events.index)
    if start is not None:
        m &= events["date"] >= pd.Timestamp(start)
    if end is not None:
        m &= events["date"] <= pd.Timestamp(end)
    return events[m].reset_index(drop=True)


def dwell_days(series: pd.Series, start: pd.Timestamp, exit_level: float) -> int | float:
    """从 start 开始，序列持续高于 exit_level 的交易日数（直到首次跌破）。"""
    s = series.loc[start:]
    below = np.flatnonzero(s.to_numpy(dtype=float) < exit_level)
    return int(below[0]) if len(below) else np.nan
