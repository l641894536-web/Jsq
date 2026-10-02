"""多因子打分：把许多单独太弱、扣费后不赚钱的因子合成一个预测值。

做法（全部只用过去数据）：
  * 特征 = analysis.features() 里的全部因子，按截至当时的 30 天滚动均值/标准差标准化，截尾到 ±4
  * 每隔 refit_days 天，用“此前 train_days 天、且未来收益在当时已经完全实现”的样本拟合岭回归
    目标 = 从下一根开盘起 horizon 小时的收益（与回测成交方式一致）
  * 预测值换算成“相对于近期波动的强度”，超过阈值才持仓 —— 只在预期收益明显大于成本时交易
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .analysis import features, forward_returns
from .strategies import bars, hold_state

_CACHE: dict = {}


def _feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    key = (df.attrs.get("symbol"), len(df), df.index[0], df.index[-1])
    if key in _CACHE:
        return _CACHE[key]
    f = features(df)
    f = f.loc[:, f.notna().mean() > 0.5]
    n = bars(df, 30 * 24)
    z = (f - f.rolling(n, min_periods=n // 3).mean()) / f.rolling(n, min_periods=n // 3).std()
    z = z.clip(-4, 4)
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = z
    return z


def predict(df: pd.DataFrame, horizon: int = 12, train_days: int = 180, refit_days: int = 30,
            ridge: float = 50.0) -> pd.Series:
    """逐根 K 线的预测收益（样本外）。前 train_days 天没有预测。"""
    X = _feature_matrix(df)
    hb = bars(df, horizon)
    y = forward_returns(df, hb).to_numpy()
    Xv = X.to_numpy()
    n = len(df)
    pred = np.full(n, np.nan)
    step = bars(df, refit_days * 24)
    train = bars(df, train_days * 24)
    for start in range(train, n, step):
        # 时刻 start 拟合：只能用目标已实现的样本 i（i + 1 + hb < start）
        hi = start - hb - 1
        lo = max(0, hi - train)
        Xt, yt = Xv[lo:hi], y[lo:hi]
        ok = np.isfinite(yt) & np.isfinite(Xt).all(axis=1)
        if ok.sum() < train // 3:
            continue
        A, b = Xt[ok], yt[ok]
        mu = b.mean()
        w = np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ (b - mu))
        end = min(n, start + step)
        Xp = Xv[start:end]
        good = np.isfinite(Xp).all(axis=1)
        p = np.full(end - start, np.nan)
        p[good] = Xp[good] @ w + mu
        pred[start:end] = p
    return pd.Series(pred, index=df.index)


def factor_model(df, horizon=12, th=1.0, train_days=180):
    """多因子模型：滚动岭回归合成全部因子；预测值超过自身近 30 天波动的 th 倍才开仓，预测转向离场。"""
    p = predict(df, horizon, train_days=train_days)
    sd = p.rolling(bars(df, 30 * 24), min_periods=bars(df, 5 * 24)).std()
    s = p / sd
    return hold_state(s > th, s < 0, s < -th, s > 0)
