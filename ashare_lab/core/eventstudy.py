"""通用事件研究：事件 vs 同一标的的平常日子，给出均值、胜率、置信区间、p 值、前后两段一致性。

推断方式（都偏保守）：
- p 值：整体时间平移置换（stats.shift_test），保留事件在时间上的扎堆结构；
- 置信区间：按“日期簇”重抽样（相隔 ≤20 个交易日的事件算一簇，不论哪个行业）；
- 证据等级用“独立簇数”而不是事件数——同一轮行情里的多次触发只算一份证据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import stats


def lookup(values: pd.DataFrame, events: pd.DataFrame) -> np.ndarray:
    out = np.full(len(events), np.nan)
    rp = values.index.get_indexer(pd.DatetimeIndex(events["date"]))
    cp = values.columns.get_indexer(events["key"])
    ok = (rp >= 0) & (cp >= 0)
    if ok.any():
        out[ok] = values.to_numpy(dtype=float)[rp[ok], cp[ok]]
    return out


def _pool_base(values: pd.DataFrame, eligible: pd.DataFrame, keys: pd.Series) -> tuple[float, float]:
    """按事件的标的构成加权的“平常日子”均值与胜率。"""
    counts = keys.value_counts()
    tot, win, n = 0.0, 0.0, 0
    for k, c in counts.items():
        pool = values[k][eligible[k]].to_numpy(dtype=float)
        pool = pool[np.isfinite(pool)]
        if len(pool) == 0:
            continue
        tot += c * pool.mean()
        win += c * np.mean(pool > 0)
        n += c
    return (tot / n, win / n) if n else (np.nan, np.nan)


def event_study(events: pd.DataFrame, metrics: dict[str, pd.DataFrame], eligible: pd.DataFrame | None,
                split_date, n_perm: int, n_boot: int, rng, alpha: float = 0.10,
                period: tuple | None = None, cluster_gap: int = 20) -> pd.DataFrame:
    """对每个评估指标输出一行统计结果。

    metrics: {名称: 宽表}，例如 {"未来20日超额": exc20}。
    eligible: 对照日的范围（宽表布尔），None 表示全部非空日。
    period: (start, end) 研究区间；对照日与平移置换都限制在这个区间内。
    """
    split = pd.Timestamp(split_date)
    lvl = int(round((1 - alpha) * 100))
    rows = []
    for name, values in metrics.items():
        if period is not None:
            values = values.loc[pd.Timestamp(period[0]):pd.Timestamp(period[1])]
        el = eligible if eligible is not None else values.notna()
        el = el.reindex(index=values.index, columns=values.columns).eq(True) & values.notna()
        vals = lookup(values, events)
        ok = np.isfinite(vals)
        ev = events[ok].reset_index(drop=True)
        v = vals[ok]
        n = len(v)
        row = {"指标": name, "n": n}
        if n == 0:
            rows.append({**row, "独立簇": 0, "两段同向": False})
            continue
        clusters = stats.date_clusters(ev["date"], cluster_gap, values.index)
        base, base_win = _pool_base(values, el, ev["key"])
        test = stats.shift_test(values, ev, el, n_perm=n_perm, rng=rng)
        lo, hi = stats.cluster_bootstrap_ci(v, clusters, n_boot=n_boot, alpha=alpha, rng=rng)
        first = (ev["date"] <= split).to_numpy()
        halves = []
        for mask in (first, ~first):
            if mask.sum() == 0:
                halves.append((0, np.nan))
                continue
            b, _ = _pool_base(values, el, ev.loc[mask, "key"])
            halves.append((int(mask.sum()), float(v[mask].mean() - b)))
        d1, d2 = halves[0][1], halves[1][1]
        rows.append({
            **row,
            "独立簇": int(len(np.unique(clusters))),
            "均值": float(v.mean()),
            "中位数": float(np.median(v)),
            "胜率": float(np.mean(v > 0)),
            "基准均值": base,
            "基准胜率": base_win,
            "差值": float(v.mean() - base),
            f"均值{lvl}%CI低": lo,
            f"均值{lvl}%CI高": hi,
            "p值": test["p"],
            "前段n": halves[0][0],
            "前段差值": d1,
            "后段n": halves[1][0],
            "后段差值": d2,
            "两段同向": bool(np.isfinite(d1) and np.isfinite(d2) and d1 * d2 > 0),
        })
    return pd.DataFrame(rows)


def add_grades(table: pd.DataFrame, rule: stats.GradeRule, p_col: str = "p值") -> pd.DataFrame:
    """对整张表做 BH 校正并给出证据等级。一张表 = 一个检验族；样本量按独立簇计。"""
    t = table.copy()
    if p_col not in t:
        t[p_col] = np.nan
    t["q值"] = stats.bh_adjust(t[p_col].to_numpy())
    n_col = t["独立簇"] if "独立簇" in t else t["n"]
    consistent = t["两段同向"] if "两段同向" in t else pd.Series(False, index=t.index)
    t["证据"] = [
        stats.GRADE_TEXT[stats.evidence_grade(int(n) if np.isfinite(n) else 0, q, bool(c), rule)]
        for n, q, c in zip(n_col, t["q值"], consistent)
    ]
    return t
