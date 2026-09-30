"""次要研究（协议第 6 节）：同一指标库用于指数/行业择时。

- 宽基：沪深300、中证500、中证1000（官方指数开高低收）+ 全A等权合成（ALLA）；
- 行业：31 个申万一级，按时点中证全指成分等权合成；
- 检验：组内各标的时间序列 Spearman IC 的平均，p = max(同一平移量的循环平移检验, 按 N/h 个独立样本的 t 检验)；
- 择时：方向调整后的信号高于自身过去 250 日中位数 = 看多，资金分 h 份滚动，次日开盘调仓，单边成本 0.1%。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as sps

from ashare_lab.data.from_qlib import read_bin, read_calendar

from . import indicators as I
from .panel import Panel


def _ew_index(P: Panel, members: np.ndarray) -> dict[str, np.ndarray]:
    """成分股等权合成：members 为 (n, m) 布尔。返回开高低收、成交额（n,）。"""
    pc = P.prev_close
    with np.errstate(all="ignore"):
        rC, rO, rH, rL = (P.C / pc - 1, P.O / pc - 1, P.H / pc - 1, P.L / pc - 1)
    ok = members & np.isfinite(rC) & np.isfinite(rO) & np.isfinite(rH) & np.isfinite(rL)
    k = ok.sum(1)

    def mean(x):
        with np.errstate(all="ignore"):
            return np.where(ok, x, 0.0).sum(1, dtype=np.float64) / k

    mC, mO, mH, mL = mean(rC), mean(rO), mean(rH), mean(rL)
    valid = k >= 5
    mC = np.where(valid, mC, 0.0)
    C = 1000 * np.cumprod(1 + mC)
    prevC = np.concatenate([[1000.0], C[:-1]])
    O = prevC * (1 + np.where(valid, mO, 0.0))
    H = np.maximum(prevC * (1 + np.where(valid, mH, 0.0)), np.maximum(O, C))
    L = np.minimum(prevC * (1 + np.where(valid, mL, 0.0)), np.minimum(O, C))
    A = np.where(members & np.isfinite(P.A), P.A, 0.0).sum(1, dtype=np.float64)
    out = {"O": O, "H": H, "L": L, "C": C, "A": A}
    first = np.argmax(valid) if valid.any() else len(valid)
    for x in out.values():
        x[:first] = np.nan
        x[~valid] = np.nan
    return out


def build_instruments(P: Panel, cfg: dict, real: bool = True) -> tuple[Panel, dict[str, list[str]]]:
    """返回标的面板（列 = 标的）与分组 {"宽基": [...], "行业": [...]}。"""
    sc = cfg["secondary"]
    cols: dict[str, dict[str, np.ndarray]] = {}
    groups: dict[str, list[str]] = {"宽基": [], "行业": []}
    traded = np.isfinite(P.C) & (np.nan_to_num(P.V) > 0)
    base = P.in_univ & traded
    q = Path(cfg["data"].get("qlib_dir", ""))
    for code in sc["instruments"]:
        if code == "ALLA":
            cols["全A等权"] = _ew_index(P, base)
            groups["宽基"].append("全A等权")
            continue
        d = q / "features" / f"sh{code}"
        if not (real and d.exists()):
            continue
        cal = read_calendar(q)
        pos = cal.get_indexer(P.dates)
        x = {}
        for k, f in (("O", "open"), ("H", "high"), ("L", "low"), ("C", "close"), ("A", "amount")):
            arr = read_bin(d / f"{f}.day.bin", len(cal)).astype(np.float64)
            v = np.where(pos >= 0, arr[np.maximum(pos, 0)], np.nan)
            v[~(v > 0)] = np.nan
            x[k] = v
        name = {"000300": "沪深300", "000905": "中证500", "000852": "中证1000"}.get(code, code)
        cols[name] = x
        groups["宽基"].append(name)
    if sc.get("include_sectors", True):
        sec = pd.Series(P.sector).fillna("")
        for s in sorted(x for x in sec.unique() if x):
            cols[f"行业{s}"] = _ew_index(P, base & (sec.to_numpy() == s)[None, :])
            groups["行业"].append(f"行业{s}")
    names = list(cols)
    stack = {k: np.column_stack([cols[c][k] for c in names]).astype(np.float32) for k in ("O", "H", "L", "C", "A")}
    n, k = stack["C"].shape
    fin = np.isfinite(stack["C"])
    Pi = Panel(P.dates, names, stack["O"], stack["H"], stack["L"], stack["C"], stack["A"], stack["A"],
               np.full((n, k), 10.0, dtype=np.float32), fin, np.zeros((n, k), np.int8),
               np.array([""] * k, dtype=object), np.cumsum(fin, 0).astype(np.int32))
    return Pi, groups


def _col_rank(a: np.ndarray) -> np.ndarray:
    return pd.DataFrame(a).rank().to_numpy(dtype=np.float64)


def col_corr(a: np.ndarray, b: np.ndarray, min_n: int = 30) -> np.ndarray:
    m = np.isfinite(a) & np.isfinite(b)
    k = m.sum(0)
    aa = np.where(m, a, 0.0)
    bb = np.where(m, b, 0.0)
    with np.errstate(all="ignore"):
        aa = np.where(m, aa - aa.sum(0) / k, 0.0)
        bb = np.where(m, bb - bb.sum(0) / k, 0.0)
        c = (aa * bb).sum(0) / np.sqrt((aa * aa).sum(0) * (bb * bb).sum(0))
    c[k < min_n] = np.nan
    return c


def group_ic_test(x: np.ndarray, y: np.ndarray, h: int, n_perm: int, rng: np.random.Generator) -> dict:
    """x, y: (T, k)。组内平均时间序列 IC 与组合版 ic_test 的 p 值。"""
    both = np.isfinite(x) & np.isfinite(y)
    xr = _col_rank(np.where(both, x, np.nan))
    yr = _col_rank(np.where(both, y, np.nan))
    ics = col_corr(xr, yr)
    obs = float(np.nanmean(ics)) if np.isfinite(ics).any() else np.nan
    T = x.shape[0]
    min_shift = max(250, 2 * h)
    p_shift = np.nan
    if np.isfinite(obs) and T > 2 * min_shift + 1:
        shifts = rng.integers(min_shift, T - min_shift, size=n_perm)
        null = np.array([np.nanmean(col_corr(np.roll(xr, s, axis=0), yr)) for s in shifts])
        null = null[np.isfinite(null)]
        p_shift = float((1 + np.sum(np.abs(null) >= abs(obs))) / (len(null) + 1))
    n = int(np.median(both.sum(0))) if both.size else 0
    n_eff = n // max(h, 1)
    p_neff = np.nan
    if np.isfinite(obs) and n_eff > 3:
        t = obs * np.sqrt((n_eff - 2) / max(1 - obs * obs, 1e-12))
        p_neff = float(2 * sps.t.sf(abs(t), n_eff - 2))
    p = max(p_shift, p_neff) if np.isfinite(p_shift) and np.isfinite(p_neff) else np.nan
    return {"ic": obs, "ic_each": ics, "p_shift": p_shift, "p_neff": p_neff, "p": p, "n": n,
            "same_sign_frac": float(np.nanmean(np.sign(ics) == np.sign(obs))) if np.isfinite(obs) else np.nan}


def timing_backtest(s: np.ndarray, O: np.ndarray, d: float, h: int, lookback: int, cost: float,
                    rows: np.ndarray) -> pd.DataFrame:
    """每个标的一行：择时 vs 买入持有（rows 为评估期布尔，长度 n）。"""
    S = pd.DataFrame(s * d)
    med = S.rolling(lookback, min_periods=lookback // 2).median()
    fav = (S > med).astype(float).where(S.notna() & med.notna()).fillna(0.0)
    expo = fav.rolling(h, min_periods=1).mean().to_numpy()
    n = O.shape[0]
    r = np.full(O.shape, np.nan)
    with np.errstate(all="ignore"):
        r[: n - 2] = O[2:] / O[1:n - 1] - 1          # t 日决定 → t+1 开盘到 t+2 开盘
    dexp = np.abs(np.diff(expo, axis=0, prepend=0.0))
    strat = expo * r - cost * dexp
    out = []
    for j in range(O.shape[1]):
        m = rows & np.isfinite(r[:, j])
        if m.sum() < 250:
            out.append({})
            continue
        a, b = strat[m, j], r[m, j]
        out.append({"择时年化": a.mean() * 252, "持有年化": b.mean() * 252,
                    "择时夏普": a.mean() / a.std() * np.sqrt(252), "持有夏普": b.mean() / b.std() * np.sqrt(252),
                    "择时最大回撤": _mdd(a), "持有最大回撤": _mdd(b), "平均仓位": float(expo[m, j].mean()),
                    "年换手": float(dexp[m, j].sum() / m.sum() * 252)})
    return pd.DataFrame(out)


def _mdd(r: np.ndarray) -> float:
    w = np.cumprod(1 + r)
    return float((w / np.maximum.accumulate(w) - 1).min())


def run_timing(P: Panel, cfg: dict, real: bool = True, log=print) -> dict:
    sc = cfg["secondary"]
    Pi, groups = build_instruments(P, cfg, real)
    log(f"标的：宽基 {len(groups['宽基'])} 个、行业 {len(groups['行业'])} 个")
    dates = Pi.dates
    rd = np.asarray((dates >= pd.Timestamp(sc["direction_period"][0])) & (dates <= pd.Timestamp(sc["direction_period"][1])))
    re_ = np.asarray((dates >= pd.Timestamp(sc["eval_period"][0])) & (dates <= pd.Timestamp(sc["eval_period"][1])))
    names = [n for cat in cfg["signals"].values() for n in cat if n not in sc["exclude_signals"]]
    idx = {g: [Pi.codes.index(c) for c in cs] for g, cs in groups.items() if cs}
    rng = np.random.default_rng(cfg.get("seed", 20260930))
    rows, timing_rows = [], []
    for name in names:
        s = I.compute(name, Pi)
        for h in sc["horizons"]:
            Y = Pi.label(h)
            # 标签窗口不跨出所属区间
            n = Pi.n
            last_d = np.where(rd)[0].max() if rd.any() else -1
            ok_d = rd & (np.arange(n) + 1 + h <= last_d)
            ok_e = re_ & (np.arange(n) + 1 + h <= n - 1)
            for g, cols in idx.items():
                xd, yd = s[ok_d][:, cols], Y[ok_d][:, cols]
                both = np.isfinite(xd) & np.isfinite(yd)
                ic_d = float(np.nanmean(col_corr(_col_rank(np.where(both, xd, np.nan)), _col_rank(np.where(both, yd, np.nan)))))
                d = float(np.sign(ic_d)) if np.isfinite(ic_d) and ic_d != 0 else np.nan
                te = group_ic_test(s[ok_e][:, cols], Y[ok_e][:, cols], h, sc["n_perm"], rng)
                rows.append({"signal": name, "h": h, "group": g, "dir_ic": ic_d, "direction": d, "ic": te["ic"],
                             "p": te["p"], "p_shift": te["p_shift"], "p_neff": te["p_neff"], "n": te["n"],
                             "same_sign_frac": te["same_sign_frac"]})
                if np.isfinite(d):
                    bt = timing_backtest(s[:, cols], Pi.O[:, cols].astype(np.float64), d, h, sc["timing_lookback"],
                                         sc["timing_cost"], re_)
                    bt.insert(0, "标的", [Pi.codes[c] for c in cols])
                    bt.insert(0, "group", g)
                    bt.insert(0, "h", h)
                    bt.insert(0, "signal", name)
                    timing_rows.append(bt)
        Pi.drop_cache()
        log(f"  {name}")
    res = pd.DataFrame(rows)
    from .stats import bh_adjust
    res["q"] = bh_adjust(res["p"].to_numpy())
    res["sig"] = (res["q"] < cfg["test"]["fdr_q"]) & (np.sign(res["ic"]) == res["direction"])
    tim = pd.concat(timing_rows, ignore_index=True) if timing_rows else pd.DataFrame()
    return {"tests": res, "timing": tim, "groups": groups}
