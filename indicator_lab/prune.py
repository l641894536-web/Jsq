"""第二轮：因子去冗余（协议 docs/indicators_pruning.md）。

- 每个指标在当日可入选股票内取居中秩分位，缺失记 0；因变量为标签的居中秩分位；
- 每个横截面回归都含截距、市值层哑变量、申万一级行业哑变量；
- 前向逐步选择只用发现集：每步加入增量系数 NW |t| 最大者，最大 |t| ≤ 3 时停止；
- 验证集：已选因子的联合回归（确认），未入选指标控制已选因子后的增量 t（排除/边缘/遗漏）；
- 合成分数 = Σ 发现集联合回归系数 × 秩分位，做多前 10% 的可交易性。
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from . import indicators as I
from .panel import Panel
from .stats import ann_excess, block_ci, nw_t
from .xsec import backtest_rows, build_context, xs_rank

ENTRY_T = 3.0
MAX_FACTORS = 20


def build_U(P: Panel, rows: np.ndarray, E: np.ndarray, names: list[str], log=print) -> np.ndarray:
    """(阶段行, 股票, 指标) 的居中秩分位，float16，缺失 = 0。"""
    U = np.zeros((len(rows), P.m, len(names)), dtype=np.float16)
    t0 = time.time()
    for k, name in enumerate(names):
        a = I.compute(name, P)[rows]
        u, _ = xs_rank(np.where(E & np.isfinite(a), a, np.nan))
        U[:, :, k] = np.nan_to_num(u, nan=0.0)
        if k % 10 == 9:
            P.drop_cache()
            log(f"  秩分位 {k + 1}/{len(names)}  {time.time() - t0:.0f}s")
    P.drop_cache()
    return U


def _baseline(tier: np.ndarray, sec: np.ndarray) -> np.ndarray:
    cols = [np.ones(len(tier))]
    for g in (1, 2, 3):
        c = (tier == g).astype(np.float64)
        if 0 < c.sum() < len(c):
            cols.append(c)
    present = np.unique(sec)
    for s in present[1:]:
        cols.append((sec == s).astype(np.float64))
    return np.column_stack(cols)


class DayData:
    """一个持有期、一段日期的逐日回归数据（可入选 & 标签有值的股票）。"""

    def __init__(self, U, uy, E, tier, sec, day_idx):
        self.days = []
        for t in day_idx:
            cols = np.where(E[t] & np.isfinite(uy[t]))[0]
            if len(cols) < 100:
                continue
            self.days.append((t, U[t, cols, :].astype(np.float32), uy[t, cols].astype(np.float64),
                              _baseline(tier[t, cols], sec[cols]).astype(np.float32)))

    def incremental(self, S: list[int], K: int) -> np.ndarray:
        """每天：控制 基线 + S 后，每个候选的增量系数（弗里施-沃-洛弗尔）。返回 (天, K)。"""
        out = np.full((len(self.days), K), np.nan)
        for i, (_, C, y, B) in enumerate(self.days):
            C = C.astype(np.float64)
            X = np.hstack([B.astype(np.float64), C[:, S]]) if S else B.astype(np.float64)
            Q, _ = np.linalg.qr(X)
            Cr = C - Q @ (Q.T @ C)
            yr = y - Q @ (Q.T @ y)
            den = (Cr * Cr).sum(0)
            with np.errstate(all="ignore"):
                b = (Cr.T @ yr) / den
            b[den < 1e-6 * len(y)] = np.nan
            b[S] = np.nan
            out[i] = b
        return out

    def start(self) -> None:
        """逐步选择的状态：每天把全部候选与因变量对基线正交化（之后每选一个因子只做一次投影）。"""
        self.state = []
        for _, C, y, B in self.days:
            Q, _ = np.linalg.qr(B.astype(np.float64))
            C = C.astype(np.float64)
            self.state.append([C - Q @ (Q.T @ C), y - Q @ (Q.T @ y)])

    def step_betas(self, S: list[int], K: int) -> np.ndarray:
        out = np.full((len(self.state), K), np.nan)
        for i, (Cr, yr) in enumerate(self.state):
            den = (Cr * Cr).sum(0)
            with np.errstate(all="ignore"):
                b = (Cr.T @ yr) / den
            b[den < 1e-6 * len(yr)] = np.nan
            b[S] = np.nan
            out[i] = b
        return out

    def add(self, j: int) -> None:
        for st in self.state:
            Cr, yr = st
            nrm = np.sqrt((Cr[:, j] ** 2).sum())
            if nrm < 1e-9:
                continue
            q = Cr[:, j] / nrm
            st[0] = Cr - np.outer(q, q @ Cr)
            st[1] = yr - q * (q @ yr)

    def joint(self, S: list[int]) -> np.ndarray:
        """每天：基线 + S 的联合回归中 S 的系数。返回 (天, |S|)。"""
        out = np.full((len(self.days), len(S)), np.nan)
        for i, (_, C, y, B) in enumerate(self.days):
            X = np.hstack([B.astype(np.float64), C[:, S].astype(np.float64)])
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
            out[i] = b[-len(S):]
        return out


def col_t(B: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    ts, ms = [], []
    for j in range(B.shape[1]):
        r = nw_t(B[:, j], lag)
        ts.append(r["t"])
        ms.append(r["mean"])
    return np.array(ts), np.array(ms)


def forward_select(dd: DayData, names: list[str], lag: int, log=print) -> tuple[list[int], pd.DataFrame]:
    S: list[int] = []
    steps = []
    dd.start()
    for step in range(MAX_FACTORS):
        t, m = col_t(dd.step_betas(S, len(names)), lag)
        j = int(np.nanargmax(np.abs(t)))
        top = np.argsort(-np.nan_to_num(np.abs(t)))[:3]
        steps.append({"步骤": step + 1, "入选": names[j] if abs(t[j]) > ENTRY_T else "（停止）", "增量 t值": t[j],
                      "次优": "、".join(f"{names[i]}({t[i]:.1f})" for i in top[1:])})
        log(f"    第 {step + 1} 步：{names[j]} t={t[j]:.2f}")
        if not abs(t[j]) > ENTRY_T:
            break
        S.append(j)
        dd.add(j)
    dd.state = None
    return S, pd.DataFrame(steps)


def correlation_families(U: np.ndarray, day_idx: np.ndarray, E: np.ndarray, names: list[str],
                         cut: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    acc = np.zeros((len(names), len(names)))
    n = 0
    for t in day_idx[::5]:
        cols = np.where(E[t])[0]
        if len(cols) < 100:
            continue
        C = U[t, cols, :].astype(np.float64)
        sd = C.std(0)
        ok = sd > 0
        R = np.full((len(names), len(names)), np.nan)
        R[np.ix_(ok, ok)] = np.corrcoef(C[:, ok].T)
        acc += np.nan_to_num(R)
        n += 1
    R = acc / max(n, 1)
    np.fill_diagonal(R, 1.0)
    D = np.clip(1 - np.abs(R), 0, None)
    np.fill_diagonal(D, 0)
    Z = linkage(squareform(D, checks=False), method="average")
    lab = fcluster(Z, t=1 - cut, criterion="distance")
    fam = pd.DataFrame({"指标": names, "家族": lab})
    return pd.DataFrame(R, index=names, columns=names), fam


def composite_backtest(P: Panel, cfg: dict, U: np.ndarray, rows: np.ndarray, split_lab: np.ndarray,
                       S: list[int], b: np.ndarray, h: int) -> pd.DataFrame:
    """合成分数做多前 10%，各切分段的可交易性与 Rank IC。"""
    u, tr, ts = cfg["universe"], cfg["trade"], cfg["test"]
    valid = {}
    for sp in np.unique(split_lab):
        idx = np.where(split_lab == sp)[0]
        v = np.zeros(len(rows), dtype=bool)
        last_panel = rows[idx[-1]]
        v[idx[rows[idx] + 1 + h <= min(last_panel, P.n - 1)]] = True
        valid[sp] = v
    allv = np.zeros(len(rows), dtype=bool)
    for v in valid.values():
        allv |= v
    ctx = build_context(P, rows, {h: allv}, [h], u["min_listed_days"], u["limit_tol"], tr["max_sell_delay"], seed=1)
    score = np.zeros((len(rows), P.m), dtype=np.float32)
    for k, j in enumerate(S):
        score += float(b[k]) * U[:, :, j].astype(np.float32)
    score = np.where(ctx["E"], score, np.nan)
    bt = backtest_rows(score, False, ctx["E"], ctx["E_pre"], ctx["open_up_next"], ctx["R"][h], ctx["delayed"][h],
                       h, tr["top_quantile"])
    Y = ctx["Y"][h]
    J = ctx["E"] & np.isfinite(Y) & np.isfinite(score)
    us, k = xs_rank(np.where(J, score, np.nan))
    uy, _ = xs_rank(np.where(J, Y, np.nan))
    with np.errstate(all="ignore"):
        ic = np.nansum(us * uy, 1) / np.sqrt(np.nansum(us * us, 1) * np.nansum(uy * uy, 1))
    ic[k < 50] = np.nan
    out = []
    for sp, v in valid.items():
        port, bench, tau = bt["port"][v], bt["bench"][v], bt["turnover"][v]
        net = port - tr["roundtrip_cost"] * np.nan_to_num(tau, nan=1.0) - bench
        stress = port - tr["stress_cost"] * np.nan_to_num(tau, nan=1.0) - bench
        lo, hi = block_ci(net, max(ts["rc_block"], 2 * h), ts["n_boot"], 0.10, seed=h)
        r = nw_t(ic[v], max(h, ts["nw_min_lag"]))
        out.append({"持有期(日)": h, "区间": sp, "合成 IC": r["mean"], "IC t值": r["t"],
                    "年化超额(毛)": ann_excess(port - bench, h), "年化超额(净0.3%)": ann_excess(net, h),
                    "90%CI下限": lo * 252 / h, "90%CI上限": hi * 252 / h, "年化超额(净0.5%)": ann_excess(stress, h),
                    "换手/期": float(np.nanmean(tau)), "平均持股数": float(np.nanmean(bt["n_hold"][v]))})
    return pd.DataFrame(out)


def run_pruning(P: Panel, cfg: dict, split_names: list[str], log=print) -> dict:
    names = [n for cat in cfg["signals"].values() for n in cat]
    horizons = cfg["trade"]["horizons"]
    u = cfg["universe"]
    P.cache["tol"] = u["limit_tol"]
    lab = np.full(P.n, "", dtype=object)
    for sp in split_names:
        a, b = cfg["split"][sp]
        lab[(P.dates >= pd.Timestamp(a)) & (P.dates <= pd.Timestamp(b))] = sp
    rows = np.where(lab != "")[0]
    split_lab = lab[rows]
    E = P.eligible(u["min_listed_days"], u["limit_tol"])[rows]
    log(f"计算 {len(names)} 个指标的秩分位（{len(rows)} 个交易日）")
    U = build_U(P, rows, E, names, log)
    tier = P.tier[rows]
    sec = pd.Series(P.sector).fillna("")
    cats = sorted(sec.unique())
    sec_code = sec.map({c: i for i, c in enumerate(cats)}).to_numpy()
    disc_idx = np.where(split_lab == "discovery")[0]
    corr, fam = correlation_families(U, disc_idx, E, names)
    res = {"names": names, "corr": corr, "families": fam, "horizons": {}}
    for h in horizons:
        log(f"持有期 {h} 日")
        lag = max(h, cfg["test"]["nw_min_lag"])
        Y = P.label(h)[rows]
        uy, _ = xs_rank(np.where(E & np.isfinite(Y), Y, np.nan))
        last = {sp: rows[np.where(split_lab == sp)[0][-1]] for sp in np.unique(split_lab)}
        ok = np.array([rows[i] + 1 + h <= min(last[split_lab[i]], P.n - 1) for i in range(len(rows))])

        def dd_for(sp):
            return DayData(U, uy, E, tier, sec_code, np.where((split_lab == sp) & ok)[0])

        dd = dd_for("discovery")
        S, steps = forward_select(dd, names, lag, log)
        jd = dd.joint(S) if S else np.zeros((0, 0))
        tj_d, bj_d = col_t(jd, lag) if S else (np.array([]), np.array([]))
        del dd
        per = {"steps": steps, "S": [names[j] for j in S], "b": bj_d}
        table = pd.DataFrame({"因子": [names[j] for j in S], "发现集系数": bj_d, "发现集 t值": tj_d})
        excl = pd.DataFrame({"指标": names})
        for sp in [s for s in split_names if s != "discovery"]:
            dv = dd_for(sp)
            if S:
                tj, bj = col_t(dv.joint(S), lag)
                table[f"{sp}_系数"], table[f"{sp}_t值"] = bj, tj
            ti, _ = col_t(dv.incremental(S, len(names)), lag)
            excl[f"{sp}_增量t"] = ti
            del dv
        if "validation" in split_names and S:
            table["确认"] = (table["validation_t值"].abs() > 2) & (np.sign(table["validation_t值"]) == np.sign(table["发现集 t值"]))
        if "validation_增量t" in excl:
            a = excl["validation_增量t"].abs()
            excl["判定"] = np.select([excl["指标"].isin(per["S"]), a < 2, a <= 3], ["已入选", "排除", "边缘"], "仍有独立信息")
        per["table"], per["excluded"] = table, excl
        if S:
            per["composite"] = composite_backtest(P, cfg, U, rows, split_lab, S, bj_d, h)
        res["horizons"][h] = per
    return res
