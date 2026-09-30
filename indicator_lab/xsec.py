"""横截面检验（协议第 4 节第 1、4、5 步）：每个信号一次遍历，输出逐日序列。

对每个持有期 h、每个交易日 t：
- Rank IC：股票池内（可入选 & 信号有值 & 标签有值）信号秩与标签秩的相关；
- 十分组：按信号秩分 10 组的平均标签收益；
- 事件类：有事件股票平均收益 − 股票池平均收益（当日事件股 ≥ MIN_EVENTS 只）；
- 按市值分层的 IC（用全池秩在层内求相关，描述性）；
- 安慰剂：信号按固定随机置换错配到其他股票（保持每条序列的换手）后的 IC；
- 可交易回测：做多前 10%（方向由发现集决定）/ 全部事件股，含涨跌停与停牌处理。

回测口径：每天都建一个持有 h 日的子组合（资金分 h 份滚动，等价于 h 个错开调仓日的组合取平均），
子组合每 h 日调仓，换手 = 1 − 与 h 日前持仓重合的比例，成本 = 双边成本 × 换手。
基准 = 同一天可入选股票等权（不计成本）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_XS = 50       # 当日有效股票数下限
MIN_EVENTS = 5    # 事件类：当日事件股下限


def xs_rank(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """逐行平均秩（NaN 保持 NaN），返回居中秩分位 u = (秩 − 0.5)/k − 0.5 与有效个数 k。"""
    r = pd.DataFrame(a).rank(axis=1).to_numpy(dtype=np.float64)
    k = np.isfinite(r).sum(1)
    with np.errstate(all="ignore"):
        u = (r - 0.5) / k[:, None] - 0.5
    return u, k


def row_corr(u: np.ndarray, v: np.ndarray, min_n: int = MIN_XS) -> np.ndarray:
    """两组逐行居中、NaN 位置相同的数据的逐行相关系数。"""
    m = np.isfinite(u) & np.isfinite(v)
    uu = np.where(m, u, 0.0)
    vv = np.where(m, v, 0.0)
    k = m.sum(1)
    uu = uu - np.where(m, (uu.sum(1) / np.maximum(k, 1))[:, None], 0.0)
    vv = vv - np.where(m, (vv.sum(1) / np.maximum(k, 1))[:, None], 0.0)
    with np.errstate(all="ignore"):
        c = (uu * vv).sum(1) / np.sqrt((uu * uu).sum(1) * (vv * vv).sum(1))
    c[k < min_n] = np.nan
    return c


def spearman_rows(s: np.ndarray, y: np.ndarray, mask: np.ndarray, min_n: int = MIN_XS):
    """逐行 Spearman 相关（在 mask 内重新排秩，精确处理并列）。返回 (ic, u_s, u_y, k)。"""
    J = mask & np.isfinite(s) & np.isfinite(y)
    us, k = xs_rank(np.where(J, s, np.nan))
    uy, _ = xs_rank(np.where(J, y, np.nan))
    with np.errstate(all="ignore"):
        ic = np.nansum(us * uy, 1) / np.sqrt(np.nansum(us * us, 1) * np.nansum(uy * uy, 1))
    ic[k < min_n] = np.nan
    return ic, us, uy, k


def group_means(values: np.ndarray, groups: np.ndarray, valid: np.ndarray, n_groups: int) -> tuple[np.ndarray, np.ndarray]:
    """逐行分组平均：groups 为 0..n_groups-1 的整数。返回 (均值 n×G, 个数 n×G)。"""
    n = values.shape[0]
    rows = np.broadcast_to(np.arange(n)[:, None], values.shape)
    idx = (rows * n_groups + groups)[valid]
    w = values[valid].astype(np.float64)
    tot = np.bincount(idx, weights=w, minlength=n * n_groups).reshape(n, n_groups)
    cnt = np.bincount(idx, minlength=n * n_groups).reshape(n, n_groups)
    with np.errstate(all="ignore"):
        return tot / cnt, cnt


def row_top_threshold(x: np.ndarray, q: float) -> np.ndarray:
    """逐行：使“≤ 阈值的比例 ≥ q”的最小取值（NaN 忽略）。取值 ≥ 阈值者即前 (1−q)，并列全部纳入。"""
    srt = np.sort(np.where(np.isfinite(x), x, np.inf), axis=1)
    k = np.isfinite(x).sum(1)
    pos = np.clip(np.ceil(q * k).astype(int) - 1, 0, x.shape[1] - 1)
    thr = srt[np.arange(x.shape[0]), pos]
    thr[k == 0] = np.nan
    return thr


def nanmean_rows(x: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = mask & np.isfinite(x)
    k = m.sum(1)
    with np.errstate(all="ignore"):
        return np.where(m, x, 0.0).sum(1, dtype=np.float64) / k, k


def backtest_rows(sd: np.ndarray, is_event: bool, E: np.ndarray, E_pre: np.ndarray, open_up_next: np.ndarray,
                  R: np.ndarray, delayed_exit: np.ndarray, h: int, top_q: float) -> dict[str, np.ndarray]:
    """做多组合逐日（子组合）表现。sd = 方向调整后的信号（越大越看多）；事件类 sd∈{0,1}。

    R[t] = t+1 开盘买入、t+1+h 开盘（含顺延）卖出的实际收益；delayed_exit[t] = 该笔卖出是否被顺延。
    """
    fin = np.isfinite(sd)
    Es = E & fin
    if is_event:
        top = Es & (sd > 0.5)
        pre = E_pre & fin & (sd > 0.5)
    else:
        # 阈值 = 当日 90% 分位的取值；“≥阈值”与“>阈值”两档中取股票数占比最接近 10% 的一档（并列值不拆分）。
        # 连续信号两档几乎相同；离散信号（如 new_high_250 只有 0/1）避免把全部股票选进来。
        thr = row_top_threshold(np.where(Es, sd, np.nan), 1 - top_q)[:, None]
        with np.errstate(invalid="ignore"):
            ge, gt = Es & (sd >= thr), Es & (sd > thr)
            k = np.maximum(Es.sum(1), 1)
            n_ge, n_gt = ge.sum(1), gt.sum(1)
            use_gt = (n_gt > 0) & (np.abs(n_gt / k - top_q) < np.abs(n_ge / k - top_q))
            top = np.where(use_gt[:, None], gt, ge)
            pre = E_pre & fin & np.where(use_gt[:, None], sd > thr, sd >= thr)
    p, nh = nanmean_rows(R, top)
    b, _ = nanmean_rows(R, E)
    prev = np.zeros_like(top)
    prev[h:] = top[:-h]
    with np.errstate(all="ignore"):
        tau = 1 - (top & prev).sum(1) / top.sum(1)
        blocked = (pre & open_up_next).sum(1) / pre.sum(1)
        dly = (top & delayed_exit).sum(1) / top.sum(1)
    tau[top.sum(1) == 0] = np.nan
    return {"port": p, "bench": b, "turnover": tau, "blocked": blocked, "delayed": dly, "n_hold": nh.astype(float)}


def analyze_signal(sig: np.ndarray, ctx: dict, horizons: list[int], is_event: bool,
                   directions: dict[int, float] | None, top_q: float) -> dict[int, pd.DataFrame]:
    """一个信号在阶段行（ctx['rows']）上的全部逐日序列。directions=None 时不做回测。"""
    rows = ctx["rows"]
    s = sig[rows]
    E = ctx["E"]
    out = {}
    s_pl = s[:, ctx["perm"]]
    for h in horizons:
        y = ctx["Y"][h]
        valid_rows = ctx["valid"][h]
        ic, us, uy, k = spearman_rows(s, y, E)
        cols: dict[str, np.ndarray] = {"ic": ic, "n": k.astype(float)}
        # 十分组
        J = np.isfinite(us)
        dec = np.clip(np.floor((np.where(J, us, 0) + 0.5) * 10), 0, 9).astype(np.int64)
        dm, _ = group_means(y, dec, J, 10)
        for g in range(10):
            cols[f"d{g + 1}"] = dm[:, g]
        # 市值分层 IC（全池秩，层内相关）
        tier = ctx["tier"]
        for g, name in ((3, "ic_t300"), (2, "ic_t500"), (1, "ic_t1000"), (0, "ic_tsmall")):
            mg = J & (tier == g)
            cols[name] = row_corr(np.where(mg, us, np.nan), np.where(mg, uy, np.nan))
        # 事件：事件股 − 股票池
        if is_event:
            Jy = E & np.isfinite(s) & np.isfinite(y)
            ev_mean, n_ev = nanmean_rows(y, Jy & (s > 0.5))
            uni_mean, _ = nanmean_rows(y, Jy)
            spread = ev_mean - uni_mean
            spread[n_ev < MIN_EVENTS] = np.nan
            cols.update({"ev_ret": ev_mean, "uni_ret": uni_mean, "spread": spread, "n_ev": n_ev.astype(float)})
        # 安慰剂
        cols["ic_placebo"] = spearman_rows(s_pl, y, E)[0]
        # 回测
        if directions is not None:
            d = directions.get(h, np.nan)
            if np.isfinite(d) and d != 0:
                sd = s if is_event else s * d
                bt = backtest_rows(sd, is_event, E, ctx["E_pre"], ctx["open_up_next"], ctx["R"][h], ctx["delayed"][h],
                                   h, top_q)
                cols.update(bt)
        df = pd.DataFrame(cols, index=ctx["dates"])
        df.loc[~valid_rows] = np.nan
        out[h] = df.astype(np.float32)
    return out


def build_context(P, rows: np.ndarray, valid: dict[int, np.ndarray], horizons: list[int], min_listed: int, tol: float,
                  max_delay: int, seed: int) -> dict:
    """阶段上下文：只取阶段行，避免重复切片。valid[h] 为阶段行内标签窗口不跨出所属切分段的行。"""
    E_full = P.eligible(min_listed, tol)
    hits = P.limit_hits(tol)
    traded = np.isfinite(P.C) & (np.nan_to_num(P.V) > 0)
    nxt_open = np.zeros_like(P.in_univ)
    nxt_open[:-1] = np.isfinite(P.O[1:])
    E_pre = P.in_univ & (P.age >= min_listed) & traded & nxt_open
    open_up_next = np.zeros_like(P.in_univ)
    open_up_next[:-1] = hits["open_up"][1:]
    _, delayed = P.exit_table(max_delay, tol)
    ctx = {
        "rows": rows,
        "dates": P.dates[rows],
        "E": E_full[rows],
        "E_pre": E_pre[rows],
        "open_up_next": open_up_next[rows],
        "tier": P.tier[rows],
        "Y": {h: P.label(h)[rows] for h in horizons},
        "R": {h: P.trade_return(h, max_delay, tol)[rows] for h in horizons},
        "delayed": {},
        "valid": valid,
        "perm": np.random.default_rng(seed).permutation(P.m),
    }
    for h in horizons:
        d = np.zeros((P.n, P.m), dtype=bool)
        d[: P.n - 1 - h] = delayed[1 + h:]
        ctx["delayed"][h] = d[rows]
    return ctx
