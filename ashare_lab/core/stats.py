"""统计检验工具：自助法置信区间、随机日期置换检验、Newey-West、BH 多重检验、证据分级。

设计原则：
- A股十年样本里，真正独立的“主线/拥挤/大跌”事件往往只有几个到几十个，
  所以每个结论都必须同时报告样本数、置信区间、相对基准的差异、前后两段是否一致。
- 事件的前瞻窗口相互重叠，普通 t 检验会高估显著性，因此默认用
  “同一标的随机日期置换检验”：把事件替换成同一标的的随机交易日，看事件均值是否异常。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sps


def clean(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[np.isfinite(a)]


def bootstrap_ci(x, n_boot: int = 2000, alpha: float = 0.10, stat=np.mean, rng=None) -> tuple[float, float]:
    """事件层面的自助法置信区间（事件已去簇，可视为近似独立）。"""
    a = clean(x)
    if len(a) < 3:
        return (np.nan, np.nan)
    rng = rng if rng is not None else np.random.default_rng(0)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    bs = stat(a[idx], axis=1)
    lo, hi = np.quantile(bs, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def block_bootstrap_mean_ci(x, block: int = 20, n_boot: int = 2000, alpha: float = 0.10, rng=None) -> tuple[float, float]:
    """移动块自助法：用于有自相关的日度序列（如策略日收益差）。"""
    a = clean(x)
    n = len(a)
    if n < 2 * block:
        return (np.nan, np.nan)
    rng = rng if rng is not None else np.random.default_rng(0)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = a[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def random_date_test(values: pd.DataFrame, events: pd.DataFrame, eligible: pd.DataFrame | None = None,
                     n_perm: int = 2000, rng=None) -> dict:
    """随机日期置换检验。

    values: 宽表（日期×标的）的评估指标，如未来20日超额收益。
    events: DataFrame[date, key]。
    eligible: 宽表布尔掩码，定义“可比的随机日”（默认=指标非空）。
    零假设：事件日的指标与同一标的的随机可比日没有差别。
    返回 obs（事件均值）、base（按事件标的构成加权的基准均值）、p（双侧）。
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    if eligible is None:
        eligible = values.notna()
    obs_vals, keys = [], []
    for d, k in zip(events["date"], events["key"]):
        v = values.at[d, k] if (d in values.index and k in values.columns) else np.nan
        if np.isfinite(v):
            obs_vals.append(v)
            keys.append(k)
    n = len(obs_vals)
    out = {"n": n, "obs": np.nan, "base": np.nan, "p": np.nan, "base_win": np.nan}
    if n == 0:
        return out
    obs = float(np.mean(obs_vals))
    key_counts = pd.Series(keys).value_counts()
    draws = np.zeros(n_perm)
    base_sum = 0.0
    base_win_sum = 0.0
    for k, cnt in key_counts.items():
        pool = values[k][eligible[k].eq(True)].to_numpy(dtype=float)
        pool = pool[np.isfinite(pool)]
        if len(pool) == 0:
            return out
        draws += rng.choice(pool, size=(cnt, n_perm), replace=True).sum(axis=0)
        base_sum += cnt * pool.mean()
        base_win_sum += cnt * np.mean(pool > 0)
    draws /= n
    base = base_sum / n
    p = (1 + np.sum(np.abs(draws - base) >= abs(obs - base) - 1e-15)) / (n_perm + 1)
    out.update(obs=obs, base=float(base), p=float(p), base_win=float(base_win_sum / n))
    return out


def date_clusters(dates, gap: int = 20, calendar: pd.DatetimeIndex | None = None) -> np.ndarray:
    """把时间上挨得近的事件归为一簇（不区分标的）：从簇内第一个事件起 gap 个交易日内的事件同簇。

    同一轮行情里多个行业/多次触发的事件高度相关，统计推断应以“簇”为独立单位。
    簇的跨度封顶为 gap 日——否则事件密集时（几十个行业、几百个事件）会一路串成跨越数年的一个簇。
    返回与输入同顺序的簇编号。
    """
    d = pd.DatetimeIndex(dates)
    if len(d) == 0:
        return np.array([], dtype=int)
    pos = calendar.get_indexer(d) if calendar is not None else np.asarray((d - d.min()).days * 5 // 7)
    order = np.argsort(pos, kind="stable")
    sp = pos[order]
    cl_sorted = np.empty(len(sp), dtype=int)
    cid, start = -1, None
    for i, p in enumerate(sp):
        if start is None or p - start > gap:
            cid += 1
            start = p
        cl_sorted[i] = cid
    out = np.empty(len(d), dtype=int)
    out[order] = cl_sorted
    return out


def cluster_bootstrap_ci(x, clusters, n_boot: int = 2000, alpha: float = 0.10, rng=None) -> tuple[float, float]:
    """按簇重抽样的均值置信区间。"""
    x = np.asarray(x, dtype=float)
    clusters = np.asarray(clusters)
    ok = np.isfinite(x)
    x, clusters = x[ok], clusters[ok]
    uniq = np.unique(clusters)
    if len(uniq) < 3:
        return (np.nan, np.nan)
    rng = rng if rng is not None else np.random.default_rng(0)
    sums = np.array([x[clusters == c].sum() for c in uniq])
    cnts = np.array([(clusters == c).sum() for c in uniq])
    pick = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def cluster_bootstrap_diff(y, group, clusters, n_boot: int = 2000, alpha: float = 0.10, rng=None) -> dict:
    """两组均值差（group=True 组 − False 组）的按簇自助法：给出差值、置信区间和双侧 p 值。"""
    y = np.asarray(y, dtype=float)
    g = np.asarray(group, dtype=bool)
    c = np.asarray(clusters)
    ok = np.isfinite(y)
    y, g, c = y[ok], g[ok], c[ok]
    out = {"diff": np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan}
    if g.sum() == 0 or (~g).sum() == 0:
        return out
    out["diff"] = float(y[g].mean() - y[~g].mean())
    uniq = np.unique(c)
    if len(uniq) < 4:
        return out
    rng = rng if rng is not None else np.random.default_rng(0)
    s1 = np.array([y[(c == u) & g].sum() for u in uniq])
    n1 = np.array([((c == u) & g).sum() for u in uniq])
    s0 = np.array([y[(c == u) & ~g].sum() for u in uniq])
    n0 = np.array([((c == u) & ~g).sum() for u in uniq])
    pick = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    with np.errstate(all="ignore"):
        d = s1[pick].sum(1) / n1[pick].sum(1) - s0[pick].sum(1) / n0[pick].sum(1)
    d = d[np.isfinite(d)]
    if len(d) < 50:
        return out
    out["lo"], out["hi"] = (float(v) for v in np.quantile(d, [alpha / 2, 1 - alpha / 2]))
    out["p"] = float(min(1.0, 2 * min(np.mean(d <= 0), np.mean(d >= 0)) + 1 / len(d)))
    return out


def cluster_bootstrap(fn, clusters, n_boot: int = 2000, alpha: float = 0.10, rng=None) -> dict:
    """通用的按簇自助法：fn(行下标数组) → 统计量。返回统计量、置信区间、双侧 p 值（相对 0）。"""
    clusters = np.asarray(clusters)
    uniq, inv = np.unique(clusters, return_inverse=True)
    groups = [np.flatnonzero(inv == k) for k in range(len(uniq))]
    stat = fn(np.arange(len(clusters)))
    out = {"stat": float(stat) if np.isfinite(stat) else np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan, "clusters": len(uniq)}
    if len(uniq) < 4 or not np.isfinite(stat):
        return out
    rng = rng if rng is not None else np.random.default_rng(0)
    draws = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), size=len(uniq))
        v = fn(np.concatenate([groups[k] for k in pick]))
        if np.isfinite(v):
            draws.append(v)
    if len(draws) < 50:
        return out
    d = np.asarray(draws)
    out["lo"], out["hi"] = (float(v) for v in np.quantile(d, [alpha / 2, 1 - alpha / 2]))
    out["p"] = float(min(1.0, 2 * min(np.mean(d <= 0), np.mean(d >= 0)) + 1 / len(d)))
    return out


def shift_test(values: pd.DataFrame, events: pd.DataFrame, eligible: pd.DataFrame | None = None,
               n_perm: int = 2000, rng=None, min_shift: int = 60) -> dict:
    """整体时间平移置换检验（比逐个随机抽日更保守）。

    把所有事件日期整体平移同一个随机偏移量（循环），保留事件之间的时间聚集结构、
    以及指标本身的自相关；零假设下，事件日的指标均值与“平移后的伪事件日”没有差别。
    values/eligible 应已截取到研究区间。返回 obs 与双侧 p 值。
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    V = values.to_numpy(dtype=float)
    Vm = V if eligible is None else np.where(
        eligible.reindex_like(values).eq(True).to_numpy(dtype=bool), V, np.nan)
    rp = values.index.get_indexer(pd.DatetimeIndex(events["date"]))
    cp = values.columns.get_indexer(events["key"])
    ok = (rp >= 0) & (cp >= 0)
    rp, cp = rp[ok], cp[ok]
    obs_vals = V[rp, cp]
    fin = np.isfinite(obs_vals)
    rp, cp, obs_vals = rp[fin], cp[fin], obs_vals[fin]
    n = len(values.index)
    if len(obs_vals) == 0:
        return {"n": 0, "obs": np.nan, "p": np.nan}
    obs = float(obs_vals.mean())
    if n <= 2 * min_shift + 1:
        return {"n": len(obs_vals), "obs": obs, "p": np.nan}
    shifts = rng.integers(min_shift, n - min_shift, size=n_perm)
    idx = (rp[None, :] + shifts[:, None]) % n
    with np.errstate(all="ignore"):
        M = Vm[idx, cp[None, :]]
        cnt = np.isfinite(M).sum(axis=1)
        perm = np.where(cnt > 0, np.nansum(M, axis=1) / np.maximum(cnt, 1), np.nan)
    perm = perm[np.isfinite(perm)]
    if len(perm) < 20:
        return {"n": len(obs_vals), "obs": obs, "p": np.nan}
    lo = np.sum(perm <= obs)
    hi = np.sum(perm >= obs)
    p = min(1.0, 2 * (1 + min(lo, hi)) / (len(perm) + 1))
    return {"n": len(obs_vals), "obs": obs, "p": float(p)}


def circular_shift_corr_test(x: pd.Series, y: pd.Series, n_perm: int = 1000, min_shift: int = 250, rng=None) -> dict:
    """时间序列相关性的循环平移检验：保留两条序列各自的自相关，只打乱二者的对齐。

    用于“信号 vs 未来收益”的预测力检验——高度持续的信号 + 重叠的未来收益会让
    普通 t 检验、甚至 Newey-West 都过于乐观（Stambaugh 偏差/伪回归）。
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    df = pd.concat([x, y], axis=1)
    a = df.iloc[:, 0].rank().to_numpy(dtype=float)
    b = df.iloc[:, 1].rank().to_numpy(dtype=float)
    n = len(a)

    def corr(u, v):
        m = np.isfinite(u) & np.isfinite(v)
        if m.sum() < 30:
            return np.nan
        u, v = u[m], v[m]
        u = u - u.mean()
        v = v - v.mean()
        d = np.sqrt((u * u).sum() * (v * v).sum())
        return float((u * v).sum() / d) if d > 0 else np.nan

    obs = corr(a, b)
    if not np.isfinite(obs) or n <= 2 * min_shift + 1:
        return {"ic": obs, "p": np.nan}
    shifts = rng.integers(min_shift, n - min_shift, size=n_perm)
    null = np.array([corr(np.roll(a, s), b) for s in shifts])
    null = null[np.isfinite(null)]
    p = (1 + np.sum(np.abs(null) >= abs(obs))) / (len(null) + 1)
    return {"ic": obs, "p": float(p)}


def ic_test(x: pd.Series, y: pd.Series, horizon: int, n_perm: int = 1000, rng=None) -> dict:
    """预测力检验：IC + 两个 p 值，取较大者。

    - 循环平移检验：保留序列自相关，但在“信号就是目标序列自身的过去变化”时偏松；
    - 有效样本 t 检验：按 N/h 个独立样本算 t 值，偏保守。
    在随机游走上模拟，两者取大的实际误报率约 0~6.5%（名义 5%），见 tests/test_stats_size.py。
    """
    cs = circular_shift_corr_test(x, y, n_perm=n_perm, min_shift=max(250, 2 * horizon), rng=rng)
    n = int(pd.concat([x, y], axis=1).dropna().shape[0])
    n_eff = max(n // max(horizon, 1), 0)
    ic = cs["ic"]
    if np.isfinite(ic) and n_eff > 3:
        t = ic * np.sqrt((n_eff - 2) / max(1 - ic * ic, 1e-12))
        p_neff = float(2 * sps.t.sf(abs(t), n_eff - 2))
    else:
        p_neff = np.nan
    p = max(cs["p"], p_neff) if np.isfinite(cs["p"]) and np.isfinite(p_neff) else np.nan
    return {"ic": ic, "p_shift": cs["p"], "p_neff": p_neff, "p": p, "n": n, "n_eff": n_eff}


def newey_west(y, x, lags: int) -> dict:
    """一元回归 y = a + b·x 的 Newey-West(HAC) t 值；用于重叠前瞻收益的预测检验。"""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    m = np.isfinite(y) & np.isfinite(x)
    y, x = y[m], x[m]
    n = len(y)
    if n < max(30, 3 * lags) or np.std(x) == 0:
        return {"beta": np.nan, "t": np.nan, "p": np.nan, "n": n}
    X = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    u = y - X @ beta
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        G = Xu[lag:].T @ Xu[:-lag]
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv
    se = np.sqrt(max(V[1, 1], 1e-300))
    t = beta[1] / se
    p = 2 * (1 - sps.norm.cdf(abs(t)))
    return {"beta": float(beta[1]), "t": float(t), "p": float(p), "n": n}


def spearman_ic(signal: pd.Series, fwd: pd.Series) -> float:
    df = pd.concat([signal, fwd], axis=1).dropna()
    if len(df) < 30:
        return np.nan
    return float(sps.spearmanr(df.iloc[:, 0], df.iloc[:, 1]).statistic)


def bh_adjust(pvals) -> np.ndarray:
    """Benjamini-Hochberg 校正后的 q 值；NaN 保持 NaN。"""
    p = np.asarray(pvals, dtype=float)
    q = np.full_like(p, np.nan)
    m = np.isfinite(p)
    k = int(m.sum())
    if k == 0:
        return q
    pv = p[m]
    order = np.argsort(pv)
    ranked = pv[order] * k / np.arange(1, k + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(k)
    out[order] = np.minimum(ranked, 1.0)
    q[m] = out
    return q


def wilson_ci(k: int, n: int, alpha: float = 0.10) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    z = sps.norm.ppf(1 - alpha / 2)
    phat = k / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    half = z * np.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    return (float(center - half), float(center + half))


def fisher_p(k1: int, n1: int, k2: int, n2: int) -> float:
    if min(n1, n2) == 0:
        return np.nan
    return float(sps.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]]).pvalue)


def binom_p_greater(k: int, n: int, p0: float) -> float:
    if n == 0 or not np.isfinite(p0):
        return np.nan
    return float(sps.binomtest(k, n, min(max(p0, 1e-9), 1 - 1e-9), alternative="greater").pvalue)


@dataclass(frozen=True)
class GradeRule:
    a_min_n: int = 20
    b_min_n: int = 10
    min_n: int = 5


GRADE_TEXT = {
    "A": "A 强证据",
    "B": "B 中等证据",
    "C": "C 弱/不显著",
    "D": "D 样本不足",
}


def evidence_grade(n: int, q: float, consistent: bool, rule: GradeRule = GradeRule()) -> str:
    """证据分级：样本量 + 多重检验校正后的 q 值 + 前后两段方向一致。"""
    if n < rule.min_n:
        return "D"
    if not np.isfinite(q):
        return "C"
    if n >= rule.a_min_n and q < 0.05 and consistent:
        return "A"
    if n >= rule.b_min_n and q < 0.10 and consistent:
        return "B"
    return "C"


def grade_rule_from_cfg(cfg: dict) -> GradeRule:
    c = cfg.get("common", {})
    return GradeRule(c.get("grade_a_min_n", 20), c.get("grade_b_min_n", 10), c.get("grade_min_n", 5))


def describe(x) -> dict:
    a = clean(x)
    if len(a) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "p25": np.nan, "p75": np.nan, "min": np.nan, "max": np.nan}
    return {
        "n": len(a),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "p25": float(np.quantile(a, 0.25)),
        "p75": float(np.quantile(a, 0.75)),
        "min": float(a.min()),
        "max": float(a.max()),
    }
