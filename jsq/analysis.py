"""预测力分析：资金费率 / 溢价 / K 线特征 与 未来收益 的关系。

回答“这个因子到底能不能预测涨跌”，与具体买卖规则无关：
  IC         —— 因子与未来收益的 Spearman 秩相关。|IC| 0.02~0.05 在小时级已算有用
  t          —— 按重叠样本修正后的显著性，|t|>2 才值得信
  ic_h1/ic_h2 —— 前后半段样本各自的 IC，符号一致才说明不是偶然
  q1/q5      —— 因子最低/最高 20% 时的平均未来收益与上涨概率
未来收益从“下一根 K 线开盘”算起，与回测成交方式一致。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .config import IC_HORIZONS_H
from .strategies import FUNDING_Z_FLOOR, PREMIUM_Z_FLOOR, bars

FEATURE_CN = {
    "funding_ann": "资金费率(年化)",
    "funding_z_30d": "资金费率 z(30天)",
    "funding_chg_1d": "资金费率 1天变化",
    "premium": "溢价率",
    "premium_z_7d": "溢价率 z(7天)",
    "ret_1bar": "上一根K线涨跌",
    "ret_1d": "过去1天涨跌",
    "ret_3d": "过去3天涨跌",
    "ret_7d": "过去7天涨跌",
    "rsi_14": "RSI(14)",
    "bb_z_72h": "布林位置(72h)",
    "ema_gap": "EMA24/EMA168 偏离",
    "taker_buy_12h": "主动买入占比(12h)",
    "volume_z_7d": "成交量 z(7天)",
    "vol_1d": "1天波动率",
}


def features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    d = bars(df, 24)
    f = pd.DataFrame(index=df.index)
    if df["funding_ann"].notna().any():
        f["funding_ann"] = df["funding_ann"]
        f["funding_z_30d"] = ind.zscore(df["funding_ann"], 30 * d, floor=FUNDING_Z_FLOOR)
        f["funding_chg_1d"] = df["funding_ann"] - df["funding_ann"].shift(d)
    if df["prem_close"].notna().any():
        f["premium"] = df["prem_close"]
        f["premium_z_7d"] = ind.zscore(df["prem_close"], 7 * d, floor=PREMIUM_Z_FLOOR)
    f["ret_1bar"] = c.pct_change()
    f["ret_1d"] = c.pct_change(d)
    f["ret_3d"] = c.pct_change(3 * d)
    f["ret_7d"] = c.pct_change(7 * d)
    f["rsi_14"] = ind.rsi(c, 14)
    f["bb_z_72h"] = ind.zscore(c, bars(df, 72))
    f["ema_gap"] = ind.ema(c, bars(df, 24)) / ind.ema(c, bars(df, 168)) - 1
    if "taker_buy_base" in df and df["taker_buy_base"].notna().any():
        n = bars(df, 12)
        f["taker_buy_12h"] = (df["taker_buy_base"].rolling(n).sum()
                              / df["volume"].rolling(n).sum().replace(0, np.nan) - 0.5)
    f["volume_z_7d"] = ind.zscore(np.log1p(df["volume"]), 7 * d)
    f["vol_1d"] = c.pct_change().rolling(d).std()
    return f.replace([np.inf, -np.inf], np.nan)


def forward_returns(df: pd.DataFrame, horizon_bars: int) -> pd.Series:
    o = df["open"]
    return o.shift(-1 - horizon_bars) / o.shift(-1) - 1


def _rank_ic(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 30:
        return np.nan
    xr = pd.Series(x).rank().to_numpy()
    yr = pd.Series(y).rank().to_numpy()
    if xr.std() == 0 or yr.std() == 0:
        return np.nan
    return float(np.corrcoef(xr, yr)[0, 1])


def predictive_power(df: pd.DataFrame, horizons_h=IC_HORIZONS_H, min_obs: int = 200) -> pd.DataFrame:
    feats = features(df)
    rows = []
    for hh in horizons_h:
        hb = bars(df, hh)
        fwd = forward_returns(df, hb)
        for name in feats.columns:
            x = feats[name]
            m = x.notna() & fwd.notna()
            n = int(m.sum())
            if n < min_obs:
                continue
            xv, yv = x[m].to_numpy(), fwd[m].to_numpy()
            ic = _rank_ic(xv, yv)
            n_eff = max(n / hb, 3)
            t = ic * np.sqrt((n_eff - 2) / max(1 - ic ** 2, 1e-12)) if ic == ic else np.nan
            half = n // 2
            q = pd.qcut(pd.Series(xv).rank(method="first"), 5, labels=False)
            y = pd.Series(yv)
            rows.append({
                "symbol": df.attrs.get("symbol"), "feature": name, "feature_cn": FEATURE_CN.get(name, name),
                "horizon_h": hh, "n": n, "ic": ic, "t": t,
                "ic_h1": _rank_ic(xv[:half], yv[:half]), "ic_h2": _rank_ic(xv[half:], yv[half:]),
                "q1_mean": float(y[q == 0].mean()), "q5_mean": float(y[q == 4].mean()),
                "q5_minus_q1": float(y[q == 4].mean() - y[q == 0].mean()),
                "q1_up_rate": float((y[q == 0] > 0).mean()), "q5_up_rate": float((y[q == 4] > 0).mean()),
                "base_up_rate": float((y > 0).mean()),
            })
    out = pd.DataFrame(rows)
    if len(out):
        out["stable"] = (np.sign(out["ic_h1"]) == np.sign(out["ic_h2"])) & (out["t"].abs() > 2)
    return out
