"""市场环境（牛/熊/震荡）划分。

两种“实时可得”的划分（t 日只用 t 日及以前数据）+ 一种“事后标签”（用未来数据，
只能作为理论上限对照，用来衡量“环境识别滞后”到底损失多少）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BULL, BEAR, RANGE = "牛市", "熊市", "震荡"
LABELS = [BULL, RANGE, BEAR]


def regime_ma(close: pd.Series, window: int = 250, slope_window: int = 20) -> pd.Series:
    """均线法：收盘在年线上且年线上行 = 牛；收盘在年线下且年线下行 = 熊；其余 = 震荡。"""
    ma = close.rolling(window, min_periods=window).mean()
    slope = ma - ma.shift(slope_window)
    lab = pd.Series(RANGE, index=close.index, dtype=object)
    lab[(close > ma) & (slope > 0)] = BULL
    lab[(close < ma) & (slope < 0)] = BEAR
    lab[ma.isna() | slope.isna()] = np.nan
    return lab


def regime_momentum(close: pd.Series, window: int = 120, up: float = 0.15, down: float = -0.15) -> pd.Series:
    """动量法：过去 window 日涨幅 > up = 牛；< down = 熊；其余 = 震荡。"""
    r = close / close.shift(window) - 1
    lab = pd.Series(RANGE, index=close.index, dtype=object)
    lab[r > up] = BULL
    lab[r < down] = BEAR
    lab[r.isna()] = np.nan
    return lab


def regime_oracle(close: pd.Series, window: int = 120, up: float = 0.15, down: float = -0.15) -> pd.Series:
    """事后标签：未来 window 日涨跌幅（用了未来数据！只作上限对照）。"""
    r = close.shift(-window) / close - 1
    lab = pd.Series(RANGE, index=close.index, dtype=object)
    lab[r > up] = BULL
    lab[r < down] = BEAR
    lab[r.isna()] = np.nan
    return lab


def persist(labels: pd.Series, n: int) -> pd.Series:
    """因果平滑：新状态连续出现 n 天才切换过去（t 日只用 t 日及以前的标签），减少来回抖动。"""
    if n <= 1:
        return labels
    vals = labels.to_numpy(dtype=object)
    out = np.empty(len(vals), dtype=object)
    cur, cand, run = None, None, 0
    for i, v in enumerate(vals):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out[i] = np.nan  # 缺失保持缺失（例如事后标签末尾），不向前填充
            continue
        if cur is None:
            cur = v
        elif v != cur:
            run = run + 1 if v == cand else 1
            cand = v
            if run >= n:
                cur, run, cand = v, 0, None
        else:
            run, cand = 0, None
        out[i] = cur
    return pd.Series(out, index=labels.index, dtype=object)


def regime_summary(labels: pd.Series) -> pd.DataFrame:
    lab = labels.dropna()
    if lab.empty:
        return pd.DataFrame()
    runs = (lab != lab.shift()).cumsum()
    seg = lab.groupby(runs).agg(["first", "size"])
    rows = []
    for name in LABELS:
        sizes = seg.loc[seg["first"] == name, "size"]
        rows.append({
            "环境": name,
            "占比": float((lab == name).mean()),
            "段数": int(len(sizes)),
            "平均持续(日)": float(sizes.mean()) if len(sizes) else np.nan,
            "中位持续(日)": float(sizes.median()) if len(sizes) else np.nan,
        })
    return pd.DataFrame(rows)


def transition_matrix(labels: pd.Series) -> pd.DataFrame:
    lab = labels.dropna()
    nxt = lab.shift(-1)
    m = pd.crosstab(lab[:-1], nxt[:-1], normalize="index")
    return m.reindex(index=LABELS, columns=LABELS).fillna(0.0)
