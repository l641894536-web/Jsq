"""逐日序列的汇总统计：Newey-West 均值 t、BH-FDR、最大 t 统计量自助法（Reality Check）、参数平台。"""

from __future__ import annotations

import numpy as np
import scipy.stats as sps

from ashare_lab.core.stats import bh_adjust  # noqa: F401  （统一出口）


def nw_se(x: np.ndarray, lag: int) -> float:
    """均值的 Newey-West 标准误（Bartlett 权重），忽略 NaN（剩余部分视为连续序列）。"""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    n = len(a)
    if n < max(30, 3 * lag):
        return np.nan
    e = a - a.mean()
    s = e @ e / n
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    return float(np.sqrt(max(s, 1e-300) / n))


def nw_t(x: np.ndarray, lag: int) -> dict:
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    se = nw_se(a, lag)
    if not np.isfinite(se) or se == 0:
        return {"mean": float(a.mean()) if len(a) else np.nan, "t": np.nan, "p": np.nan, "n": len(a), "se": np.nan}
    m = float(a.mean())
    t = m / se
    return {"mean": m, "t": t, "p": float(2 * sps.norm.sf(abs(t))), "n": len(a), "se": se}


def stationary_bootstrap_idx(n: int, mean_block: int, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano 平稳自助法的下标（循环）。"""
    idx = np.empty(n, dtype=np.int64)
    idx[0] = rng.integers(n)
    new = rng.random(n) < 1.0 / mean_block
    starts = rng.integers(n, size=n)
    for i in range(1, n):
        idx[i] = starts[i] if new[i] else (idx[i - 1] + 1) % n
    return idx


def reality_check(X: np.ndarray, se: np.ndarray, n_boot: int, block: int, seed: int) -> np.ndarray:
    """最大 |t| 自助法：X 为 T×K 的逐日序列（NaN 允许），se 为各列 NW 标准误。

    返回各列经族错误率校正的 p 值：P(max_k |t*_k| ≥ |t_k|)。t*_k = (自助均值 − 原均值)/se_k。
    """
    T, K = X.shape
    mu = np.nanmean(X, 0)
    ok = np.isfinite(se) & (se > 0)
    t = np.where(ok, mu / np.where(ok, se, 1), np.nan)
    rng = np.random.default_rng(seed)
    Xf = np.where(np.isfinite(X), X, 0.0)
    cnt = np.isfinite(X).astype(np.float64)
    mx = np.empty(n_boot)
    for b in range(n_boot):
        idx = stationary_bootstrap_idx(T, block, rng)
        with np.errstate(all="ignore"):
            mb = Xf[idx].sum(0) / cnt[idx].sum(0)
            tb = np.abs((mb - mu) / se)
        mx[b] = np.nanmax(np.where(ok, tb, np.nan))
    p = np.full(K, np.nan)
    p[ok] = (1 + (mx[None, :] >= np.abs(t[ok])[:, None]).sum(1)) / (n_boot + 1)
    return p


def plateau(tvals: dict[str, float], family: list[str], ratio: float) -> dict[str, bool]:
    """参数平台：该参数的相邻参数须与它同号，且 |t| ≥ ratio × 它的 |t|。"""
    out = {}
    for i, name in enumerate(family):
        t0 = tvals.get(name, np.nan)
        nbs = [family[j] for j in (i - 1, i + 1) if 0 <= j < len(family)]
        ok = np.isfinite(t0)
        for nb in nbs:
            t1 = tvals.get(nb, np.nan)
            ok = ok and np.isfinite(t1) and np.sign(t1) == np.sign(t0) and abs(t1) >= ratio * abs(t0)
        out[name] = bool(ok)
    return out


def ann_excess(x: np.ndarray, h: int) -> float:
    """逐日子组合超额（每份资金持有 h 日）→ 年化（252 日，简单乘法）。"""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    return float(a.mean() * 252 / h) if len(a) else np.nan


def block_ci(x: np.ndarray, block: int, n_boot: int, alpha: float, seed: int) -> tuple[float, float]:
    """移动块自助法均值置信区间。"""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    n = len(a)
    if n < 2 * block:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = a[idx].mean(1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)
