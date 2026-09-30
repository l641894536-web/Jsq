"""模拟股票面板（协议第 0 步：误报率与检验力校准）。

零假设版本：对数收益 = β·市场 + 行业 + 个股（波动率聚集、厚尾），**未来收益与任何过去信息独立**，
且对数收益关于 0 对称（因此任何信号与未来收益的秩相关期望为 0）。保留真实数据里会干扰检验的结构：
市场/行业共同波动、波动率与 β 的个股差异、停牌、上市/退市、涨跌停截断、量价相关。
埋入信号版本（plant > 0）：次日对数收益的期望 = −plant × 个股波动 × 过去 5 日收益的横截面标准分（短期反转）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .panel import Panel


def synthetic_panel(n_stocks: int = 1500, start: str = "2010-01-04", end: str = "2022-12-30", seed: int = 0,
                    plant: float = 0.0, n_sector: int = 28) -> Panel:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    n, m = len(dates), n_stocks
    beta = rng.uniform(0.5, 1.5, m)
    sector = rng.integers(0, n_sector, m)
    base_vol = np.exp(rng.normal(np.log(0.018), 0.35, m))
    # 市场波动状态（对数 AR(1)）与个股波动状态
    lv_m = np.zeros(n)
    for t in range(1, n):
        lv_m[t] = 0.99 * lv_m[t - 1] + 0.08 * rng.standard_normal()
    f = 0.012 * np.exp(lv_m) * rng.standard_t(5, n) * np.sqrt(3 / 5)
    g = 0.007 * rng.standard_normal((n, n_sector))
    lv = np.zeros((n, m))
    for t in range(1, n):
        lv[t] = 0.98 * lv[t - 1] + 0.05 * rng.standard_normal(m)
    sig = base_vol[None, :] * np.exp(lv)
    eps = rng.standard_t(4, (n, m)) / np.sqrt(2.0)
    r = beta[None, :] * f[:, None] + g[:, sector] + sig * eps
    # 上市、退市、停牌
    listed = np.where(rng.random(m) < 0.6, 0, rng.integers(0, int(n * 0.85), m))
    delist = np.where(rng.random(m) < 0.05, rng.integers(n // 3, n, m), n)
    alive = (np.arange(n)[:, None] >= listed[None, :]) & (np.arange(n)[:, None] < delist[None, :])
    susp = np.zeros((n, m), dtype=bool)
    start_s = rng.random((n, m)) < 0.002
    length = rng.geometric(0.2, (n, m))
    for t, j in zip(*np.nonzero(start_s)):
        susp[t:t + length[t, j], j] = True
    trade = alive & ~susp
    up, dn = np.log(1.1), np.log(0.9)   # 涨跌停 ±10%（对数下不对称，影响可忽略）
    # 逐日生成（埋入信号需要用到过去收益）
    logC = np.zeros((n, m))
    rr = np.zeros((n, m))
    past = np.zeros((6, m))       # 最近 6 个对数收益（环形）
    for t in range(n):
        x = r[t].copy()
        if plant > 0 and t >= 5:
            r5 = past[:5].sum(0)
            z = (r5 - r5.mean()) / (r5.std() + 1e-12)
            x = x - plant * sig[t] * z
        x = np.clip(x, dn, up)
        x[~trade[t]] = 0.0
        rr[t] = x
        logC[t] = (logC[t - 1] if t else 0.0) + x
        past = np.roll(past, 1, axis=0)
        past[0] = x
    C = 10 * np.exp(logC)
    prevC = np.vstack([C[:1], C[:-1]])
    gap = np.clip(0.25 * rr + 0.3 * sig * rng.standard_normal((n, m)), dn, up)
    O = prevC * np.exp(gap)
    hi_ext = np.abs(rng.normal(0, 0.5, (n, m))) * sig
    lo_ext = np.abs(rng.normal(0, 0.5, (n, m))) * sig
    H = np.minimum(np.maximum(O, C) * np.exp(hi_ext), prevC * 1.1)
    L = np.maximum(np.minimum(O, C) * np.exp(-lo_ext), prevC * 0.9)
    H = np.where(rr >= up - 1e-9, C, H)
    L = np.where(rr <= dn + 1e-9, C, L)
    lvol = np.zeros((n, m))
    for t in range(1, n):
        lvol[t] = 0.9 * lvol[t - 1] + 0.3 * rng.standard_normal(m)
    size = rng.normal(0, 1, m)
    V = np.exp(12 + size[None, :] + lvol + 8 * np.abs(rr))
    A = V * C
    for x in (O, H, L, C, V, A):
        x[~trade] = np.nan
    in_univ = alive & (np.arange(n)[:, None] >= listed[None, :] + 20)
    age = np.cumsum(np.isfinite(C), axis=0).astype(np.int32)
    rk = pd.Series(size).rank(pct=True).to_numpy()
    tier_s = np.select([rk > 0.9, rk > 0.75, rk > 0.45], [3, 2, 1], 0).astype(np.int8)
    tier = np.broadcast_to(tier_s, (n, m)).copy()
    codes = [f"{600000 + j:06d}" for j in range(m)]
    sec = np.array([f"S{k:02d}" for k in sector], dtype=object)
    f32 = lambda a: a.astype(np.float32)  # noqa: E731
    return Panel(dates, codes, f32(O), f32(H), f32(L), f32(C), f32(V), f32(A),
                 np.full((n, m), 0.10, dtype=np.float32), in_univ, tier, sec, age)
