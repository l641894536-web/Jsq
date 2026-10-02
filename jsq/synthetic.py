"""合成数据：离线时用来跑通整套流程和单元测试。结果没有任何交易意义。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import INTERVAL_MS
from .data import paths

# 名称: (年化波动, 趋势强度, 资金费率反向效应强度)
PRESETS = {
    "SYNTREND": (0.6, 1.0, 0.0),    # 有持续趋势
    "SYNFADE": (0.5, 0.0, 1.0),     # 拥挤后回归，资金费率反向有效
    "SYNNOISE": (0.4, 0.0, 0.0),    # 纯随机游走
}


def make_symbol(name: str, interval: str = "1h", days: int = 540, seed: int = 0,
                vol_ann: float = 0.5, trend: float = 0.0, fade: float = 0.0, start="2024-01-01"):
    rng = np.random.default_rng(seed)
    step = INTERVAL_MS[interval]
    bh = step / 3_600_000
    n = int(days * 24 / bh)
    bpy = 365 * 24 / bh
    sig = vol_ann / np.sqrt(bpy)
    # 随机波动率
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.995 * lv[i - 1] + 0.05 * rng.standard_normal()
    vol = sig * np.exp(lv)
    # 趋势状态（马尔可夫切换）
    regime = np.zeros(n)
    s = 1.0
    for i in range(n):
        if rng.random() < 1 / (24 * 20 / bh):
            s = -s
        regime[i] = s
    eps = rng.standard_normal(n)
    ret = np.zeros(n)
    crowd = np.zeros(n)
    prem = np.zeros(n)
    a = 2 / (72 / bh + 1)
    for i in range(n):
        c_prev = crowd[i - 1] if i else 0.0
        p_prev = prem[i - 1] if i else 0.0
        mu = trend * regime[i] * sig * 0.06 - fade * (p_prev - 1e-4) / 2e-4 * sig * 0.05
        ret[i] = mu + vol[i] * eps[i]
        crowd[i] = (1 - a) * c_prev + a * ret[i] / sig
        prem[i] = 1e-4 + 6e-4 * crowd[i] * 3 + 1e-4 * rng.standard_normal()
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[100.0], close[:-1]])
    wick = np.abs(rng.standard_normal((2, n))) * vol * 0.6
    high = np.maximum(open_, close) * (1 + wick[0])
    low = np.minimum(open_, close) * (1 - wick[1])
    volume = np.exp(rng.normal(8, 0.3, n)) * (1 + 3 * np.abs(ret) / vol)
    tb = np.clip(0.5 + 0.15 * ret / vol + 0.03 * rng.standard_normal(n), 0.05, 0.95) * volume
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    ot = t0 + np.arange(n) * step
    kl = pd.DataFrame({"open_time": ot, "open": open_, "high": high, "low": low, "close": close,
                       "volume": volume, "close_time": ot + step - 1, "quote_volume": volume * close,
                       "trades": (volume / 10).astype(int), "taker_buy_base": tb, "taker_buy_quote": tb * close})
    pr = pd.DataFrame({"open_time": ot, "open": prem, "high": prem + 5e-5, "low": prem - 5e-5, "close": prem})
    # 每 8 小时结算：F = 平均溢价 + clamp(0.01% - 平均溢价, ±0.05%)
    per = max(1, int(round(8 / bh)))
    rows = []
    for j in range(per, n + 1, per):
        p = prem[j - per:j].mean()
        f = float(np.clip(p + np.clip(1e-4 - p, -5e-4, 5e-4), -0.0075, 0.0075))
        rows.append({"funding_time": t0 + j * step + 3, "funding_rate": f, "mark_price": close[j - 1]})
    return kl, pr, pd.DataFrame(rows)


def make_dataset(data_dir: Path, interval: str = "1h", days: int = 540, seed: int = 7) -> list[str]:
    out = []
    for k, (name, (v, tr, fd)) in enumerate(PRESETS.items()):
        sym = f"{name}USDT"
        kl, pr, fu = make_symbol(sym, interval, days, seed + k, v, tr, fd)
        p = paths(data_dir, sym, interval)
        p["klines"].parent.mkdir(parents=True, exist_ok=True)
        kl.to_csv(p["klines"], index=False)
        pr.to_csv(p["premium"], index=False)
        fu.to_csv(p["funding"], index=False)
        out.append(sym)
    return out
