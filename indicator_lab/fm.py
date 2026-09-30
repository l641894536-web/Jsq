"""增量信息（协议第 4 节第 3 步）：每日横截面回归（Fama-MacBeth）。

因变量：标签的横截面居中秩分位；自变量：信号的居中秩分位 + 控制变量（ret_1、ret_20、mom_12_1、vol_20、
log_amount_20 的居中秩分位，缺失记 0）+ 市值分层哑变量 + 申万一级行业哑变量。
信号与标签在“可入选 & 信号有值 & 标签有值”内排秩；控制变量在“可入选 & 标签有值”内排秩（每个持有期只算一次）。
"""

from __future__ import annotations

import numpy as np

from .stats import nw_t
from .xsec import MIN_XS, xs_rank


def control_ranks(controls: dict[str, np.ndarray], E: np.ndarray, Y: np.ndarray) -> dict[str, np.ndarray]:
    base = E & np.isfinite(Y)
    out = {}
    for name, c in controls.items():
        u, _ = xs_rank(np.where(base & np.isfinite(c), c, np.nan))
        out[name] = np.where(base, np.nan_to_num(u, nan=0.0), np.nan).astype(np.float32)
    return out


def dummies(tier_row: np.ndarray, sector_codes: np.ndarray, n_sector: int) -> np.ndarray:
    T = np.stack([(tier_row == g) for g in (1, 2, 3)], 1).astype(np.float64)
    S = np.zeros((len(sector_codes), max(n_sector - 1, 0)))
    nz = sector_codes > 0
    S[np.where(nz)[0], sector_codes[nz] - 1] = 1.0
    return np.hstack([T, S])


def fama_macbeth(s: np.ndarray, Y: np.ndarray, E: np.ndarray, ctrl_u: dict[str, np.ndarray], tier: np.ndarray,
                 sector_codes: np.ndarray, rows_mask: np.ndarray, exclude: str | None = None) -> np.ndarray:
    """逐日信号系数序列（rows_mask 以外为 NaN）。"""
    n = s.shape[0]
    J = E & np.isfinite(s) & np.isfinite(Y)
    us, k = xs_rank(np.where(J, s, np.nan))
    uy, _ = xs_rank(np.where(J, Y, np.nan))
    names = [c for c in ctrl_u if c != exclude]
    n_sector = int(sector_codes.max()) + 1
    beta = np.full(n, np.nan)
    for t in np.where(rows_mask & (k >= MIN_XS))[0]:
        m = J[t]
        cols = [np.ones(m.sum()), us[t, m]] + [ctrl_u[c][t, m] for c in names]
        X = np.column_stack(cols + [dummies(tier[t, m], sector_codes[m], n_sector)])
        X = X[:, np.concatenate([[True, True], np.ones(len(names), bool), X[:, 2 + len(names):].std(0) > 0])]
        b, *_ = np.linalg.lstsq(X, uy[t, m], rcond=None)
        beta[t] = b[1]
    return beta


def fm_summary(beta: np.ndarray, h: int, nw_min_lag: int) -> dict:
    r = nw_t(beta, max(h, nw_min_lag))
    return {"fm_coef": r["mean"], "fm_t": r["t"], "fm_days": r["n"]}
