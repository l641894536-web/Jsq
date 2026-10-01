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

ROUND_TRIP_BPS = 14.0
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
    # 持仓量 / 多空比 / 主动买卖
    "oi_chg_4h": "持仓量4h变化",
    "oi_chg_24h": "持仓量24h变化",
    "oi_z_7d": "持仓量 z(7天)",
    "ret_4h_oi_up": "涨跌·持仓增加时(新资金)",
    "ret_4h_oi_down": "涨跌·持仓减少时(平仓)",
    "top_acct_ls_z": "大户账户多空比 z",
    "top_pos_ls_z": "大户持仓多空比 z",
    "global_ls_z": "全体账户多空比 z",
    "smart_vs_retail": "大户持仓-散户账户 多空差",
    "global_ls_chg_24h": "全体多空比24h变化",
    "taker_ls_4h": "主动买/卖量比(4h)",
    # 订单簿
    "book_imb1": "盘口失衡±1%",
    "book_imb5": "盘口失衡±5%",
    "book_imb1_4h": "盘口失衡±1%(4h均)",
    "book_imb1_z": "盘口失衡±1% z",
    # 跨标的 / 时段
    "peer_ret_1h": "参照标的1h涨跌",
    "peer_ret_4h": "参照标的4h涨跌",
    "rel_ret_1d": "相对参照1天强弱",
    "rel_ret_3d": "相对参照3天强弱",
    "offhours_ret": "美股休市期间涨跌",
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
    h4 = bars(df, 4)

    def has(col):
        return col in df and df[col].notna().mean() > 0.3

    if has("oi"):
        loi = np.log(df["oi"])
        f["oi_chg_4h"] = loi.diff(h4)
        f["oi_chg_24h"] = loi.diff(d)
        f["oi_z_7d"] = ind.zscore(loi, 7 * d)
        r4 = c.pct_change(h4)
        f["ret_4h_oi_up"] = r4.where(f["oi_chg_4h"] > 0)
        f["ret_4h_oi_down"] = r4.where(f["oi_chg_4h"] < 0)
    for col in ("top_acct_ls", "top_pos_ls", "global_ls"):
        if has(col):
            f[f"{col}_z"] = ind.zscore(np.log(df[col].where(df[col] > 0)), 7 * d)
    if has("top_pos_ls") and has("global_ls"):
        f["smart_vs_retail"] = ind.zscore(np.log(df["top_pos_ls"].where(df["top_pos_ls"] > 0))
                                          - np.log(df["global_ls"].where(df["global_ls"] > 0)), 7 * d)
        f["global_ls_chg_24h"] = np.log(df["global_ls"].where(df["global_ls"] > 0)).diff(d)
    if has("taker_ls"):
        f["taker_ls_4h"] = df["taker_ls"].rolling(h4).mean()
    if has("imb1"):
        f["book_imb1"] = df["imb1"]
        f["book_imb5"] = df["imb5"]
        f["book_imb1_4h"] = df["imb1_mean"].rolling(h4).mean()
        f["book_imb1_z"] = ind.zscore(df["imb1_mean"], 7 * d)
    if has("peer_close"):
        pc = df["peer_close"]
        f["peer_ret_1h"] = pc.pct_change(bars(df, 1))
        f["peer_ret_4h"] = pc.pct_change(h4)
        f["rel_ret_1d"] = c.pct_change(d) - pc.pct_change(d)
        f["rel_ret_3d"] = c.pct_change(3 * d) - pc.pct_change(3 * d)
    from .cross import offhours_return
    f["offhours_ret"] = offhours_return(df)
    return f.replace([np.inf, -np.inf], np.nan)


def seasonality(df: pd.DataFrame) -> pd.DataFrame:
    """按 UTC 小时 和 星期几 统计下一根 K 线的平均收益与 t 值。"""
    fwd = forward_returns(df, 1)
    t = df.index + pd.Timedelta(hours=df.attrs.get("bar_hours", 1.0))  # 信号时刻 = 收盘
    rows = []
    for kind, key in (("hour", t.hour), ("weekday", t.weekday)):
        g = fwd.groupby(np.asarray(key))
        for k, x in g:
            x = x.dropna()
            if len(x) < 30:
                continue
            sd = x.std()
            rows.append({"symbol": df.attrs.get("symbol"), "kind": kind, "key": int(k), "n": len(x),
                         "mean_bps": x.mean() * 1e4, "t": x.mean() / sd * np.sqrt(len(x)) if sd > 0 else 0,
                         "up_rate": (x > 0).mean()})
    return pd.DataFrame(rows)


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
                # 按 IC 方向做（高分位做多/低分位做空，或反之）时每笔的平均毛收益（基点）
                "edge_bps": float(np.sign(ic) * (y[q == 4].mean() - y[q == 0].mean()) / 2 * 1e4) if ic == ic else np.nan,
            })
    out = pd.DataFrame(rows)
    if len(out):
        out["stable"] = (np.sign(out["ic_h1"]) == np.sign(out["ic_h2"])) & (out["t"].abs() > 2)
        # 扣费后仍可能有利：稳定 + 每笔毛收益超过一来一回成本（默认 0.14%）
        out["tradable"] = out["stable"] & (out["edge_bps"] > ROUND_TRIP_BPS)
    return out
