"""极简向量化回测：t 日收盘出信号，(1+entry_lag) 日后开始承担收益，扣双边成本。"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 244  # A股年交易日约 242-244


def run_weights(weights: pd.DataFrame, returns: pd.DataFrame, entry_lag: int = 1, cost_bps: float = 10.0) -> pd.Series:
    """weights: t 日收盘决定的目标权重（日期×资产）；returns: 日收益。

    entry_lag=0：t 日收盘成交，赚 t+1 日收益；entry_lag=1：t+1 日收盘成交，赚 t+2 日收益。
    成本 = 单边 cost_bps × 换手（|Δw| 之和）。
    """
    w = weights.reindex(index=returns.index, columns=returns.columns).fillna(0.0)
    pos = w.shift(1 + entry_lag).fillna(0.0)
    r = returns.fillna(0.0)
    gross = (pos * r).sum(axis=1)
    turnover = pos.diff().abs().sum(axis=1).fillna(pos.abs().sum(axis=1))
    return gross - turnover * cost_bps / 1e4


def hold_every(signal_weights: pd.DataFrame, every: int) -> pd.DataFrame:
    """每 every 个交易日调仓一次，中间保持上次权重。"""
    w = signal_weights.copy()
    keep = np.zeros(len(w), dtype=bool)
    keep[::every] = True
    w[~keep] = np.nan
    return w.ffill().fillna(0.0)


def top_k_weights(score: pd.DataFrame, k: int, largest: bool = True) -> pd.DataFrame:
    rank = score.rank(axis=1, ascending=not largest, method="first")
    sel = (rank <= k) & score.notna()
    w = sel.astype(float)
    return w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def perf_stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 2:
        return {"年化收益": np.nan, "年化波动": np.nan, "夏普": np.nan, "最大回撤": np.nan, "日胜率": np.nan, "天数": len(r)}
    nav = (1 + r).cumprod()
    ann = nav.iloc[-1] ** (TRADING_DAYS / len(r)) - 1
    vol = r.std() * np.sqrt(TRADING_DAYS)
    mdd = (nav / nav.cummax() - 1).min()
    return {
        "年化收益": float(ann),
        "年化波动": float(vol),
        "夏普": float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() > 0 else np.nan,
        "最大回撤": float(mdd),
        "日胜率": float((r[r != 0] > 0).mean()) if (r != 0).any() else np.nan,
        "天数": int(len(r)),
    }


def conditional_stats(r: pd.Series, labels: pd.Series) -> pd.DataFrame:
    """按环境标签拆分策略日收益（标签取 t-1 日，即持仓决策时已知的环境）。"""
    lab = labels.shift(1).reindex(r.index)
    rows = []
    for name, sub in r.groupby(lab):
        rows.append({"环境": name, **perf_stats(sub)})
    return pd.DataFrame(rows)
