"""调度：面板 → 逐信号计算（发现+验证 或 测试）→ 汇总 → 判定。"""

from __future__ import annotations

import time
import tomllib
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from ashare_lab.core.regimes import persist, regime_ma
from ashare_lab.data.from_qlib import read_bin, read_calendar

from . import indicators as I
from .fm import control_ranks, fama_macbeth, fm_summary
from .panel import Panel
from .stats import ann_excess, bh_adjust, block_ci, nw_se, nw_t, plateau, reality_check
from .xsec import analyze_signal, backtest_rows, build_context

SPLIT_CN = {"discovery": "发现集", "validation": "验证集", "test": "测试集"}


def load_cfg(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def signal_table(cfg: dict) -> pd.DataFrame:
    rows = [(name, cat, name.startswith("ev_")) for cat, names in cfg["signals"].items() for name in names]
    return pd.DataFrame(rows, columns=["signal", "category", "event"])


def split_layout(dates: pd.DatetimeIndex, cfg: dict, stage: str, horizons: list[int]):
    """阶段行、每行所属切分段、各持有期的有效行（标签窗口不跨出所属切分段，也不跨出面板）。"""
    names = ["discovery", "validation"] if stage == "dv" else ["test"]
    lab = np.full(len(dates), "", dtype=object)
    valid = {h: np.zeros(len(dates), dtype=bool) for h in horizons}
    for nm in names:
        a, b = cfg["split"][nm]
        idx = np.where((dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b)))[0]
        if len(idx) == 0:
            continue
        lab[idx] = nm
        last = min(idx[-1], len(dates) - 1)
        for h in horizons:
            valid[h][idx[idx + 1 + h <= last]] = True
    rows = np.where(lab != "")[0]
    return rows, lab[rows], {h: v[rows] for h, v in valid.items()}


def run_signals(P: Panel, cfg: dict, stage: str, directions: dict | None = None, log=print,
                only: list[str] | None = None) -> tuple[dict, dict]:
    """逐信号计算全部逐日序列。directions=None → 方向取发现集主统计量的符号。"""
    horizons = cfg["trade"]["horizons"]
    u, t = cfg["universe"], cfg["trade"]
    P.cache["tol"] = u["limit_tol"]
    rows, split_lab, valid = split_layout(P.dates, cfg, stage, horizons)
    ctx = build_context(P, rows, valid, horizons, u["min_listed_days"], u["limit_tol"], t["max_sell_delay"],
                        seed=cfg.get("seed", 20260930))
    ctx["split"] = split_lab
    tbl = signal_table(cfg)
    if only:
        tbl = tbl[tbl.signal.isin(only)]
    daily: dict = {}
    prev_cat = None
    t0 = time.time()
    for i, (name, cat, is_ev) in enumerate(tbl.itertuples(index=False)):
        if prev_cat is not None and cat != prev_cat:
            P.drop_cache()
        prev_cat = cat
        arr = I.compute(name, P)
        res = analyze_signal(arr, ctx, horizons, bool(is_ev), None, t["top_quantile"])
        s_rows = arr[rows]
        for h in horizons:
            df = res[h]
            if directions is None:
                prim = df["spread" if is_ev else "ic"].to_numpy()
                d = float(np.sign(np.nanmean(prim[split_lab == "discovery"]))) if np.isfinite(prim[split_lab == "discovery"]).any() else np.nan
            else:
                d = float(directions.get((name, h), np.nan))
            if np.isfinite(d) and d != 0:
                sd = s_rows if is_ev else s_rows * d
                bt = backtest_rows(sd, bool(is_ev), ctx["E"], ctx["E_pre"], ctx["open_up_next"], ctx["R"][h],
                                   ctx["delayed"][h], h, t["top_quantile"])
                for k, v in bt.items():
                    df[k] = np.where(valid[h], v, np.nan).astype(np.float32)
            df["direction"] = d
        daily[name] = res
        log(f"  [{i + 1}/{len(tbl)}] {name}  累计 {time.time() - t0:.0f}s")
    return daily, ctx


def _primary(is_ev: bool) -> str:
    return "spread" if is_ev else "ic"


def summarize(daily: dict, ctx: dict, cfg: dict) -> pd.DataFrame:
    """每个 信号 × 持有期 × 切分段 一行。"""
    horizons = cfg["trade"]["horizons"]
    ts, tr = cfg["test"], cfg["trade"]
    tbl = signal_table(cfg).set_index("signal")
    split_lab = ctx["split"]
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        _summarize_into(out, daily, ctx, cfg, tbl, horizons, ts, tr, split_lab)
    return pd.DataFrame(out)


def _summarize_into(out, daily, ctx, cfg, tbl, horizons, ts, tr, split_lab) -> None:
    for name, res in daily.items():
        cat, is_ev = tbl.loc[name, "category"], bool(tbl.loc[name, "event"])
        for h in horizons:
            df = res[h]
            lag = max(h, ts["nw_min_lag"])
            for sp in [s for s in ("discovery", "validation", "test") if (split_lab == s).any()]:
                m = (split_lab == sp) & ctx["valid"][h]
                sub = df[m]
                r = {"signal": name, "category": cat, "event": is_ev, "h": h, "split": sp,
                     "direction": float(sub["direction"].iloc[0]) if len(sub) else np.nan}
                ic = nw_t(sub["ic"].to_numpy(), lag)
                icv = sub["ic"].to_numpy(dtype=float)
                r.update({"ic_mean": ic["mean"], "ic_t": ic["t"], "ic_p": ic["p"], "days": ic["n"],
                          "ic_ir": np.nanmean(icv) / np.nanstd(icv) if np.isfinite(icv).sum() > 2 else np.nan,
                          "ic_pos": np.nanmean(icv[np.isfinite(icv)] > 0) if np.isfinite(icv).any() else np.nan})
                if is_ev:
                    spr = sub["spread"].to_numpy(dtype=float)
                    ok = np.isfinite(spr)
                    sp_ = nw_t(np.where(ok, spr, 0.0), lag)      # 真实日历：无事件日记 0（见协议变更记录）
                    r.update({"spread_mean": float(spr[ok].mean()) if ok.any() else np.nan, "spread_t": sp_["t"],
                              "spread_p": sp_["p"], "ev_days": int(ok.sum()),
                              "ev_per_day": float(np.nanmean(sub["n_ev"].to_numpy()[ok])) if ok.any() else np.nan})
                pk = _primary(is_ev)
                r.update({"stat_mean": r[f"{pk}_mean"], "stat_t": r[f"{pk}_t"], "stat_p": r[f"{pk}_p"]})
                dm = np.array([np.nanmean(sub[f"d{g}"].to_numpy(dtype=float)) for g in range(1, 11)])
                for g in range(10):
                    r[f"d{g + 1}"] = dm[g]
                tb = nw_t((sub["d10"] - sub["d1"]).to_numpy(), lag)
                r.update({"top_bottom": tb["mean"], "top_bottom_t": tb["t"]})
                okd = np.isfinite(dm)
                r["mono"] = float(pd.Series(dm[okd]).corr(pd.Series(np.arange(10)[okd]), method="spearman")) if okd.sum() >= 3 else np.nan
                r["placebo_t"] = nw_t(sub["ic_placebo"].to_numpy(), lag)["t"]
                for tcol in ("ic_t300", "ic_t500", "ic_t1000", "ic_tsmall"):
                    x = nw_t(sub[tcol].to_numpy(), lag)
                    r[f"{tcol}_mean"], r[f"{tcol}_tstat"] = x["mean"], x["t"]
                if "port" in sub:
                    port, bench, tau = (sub[c].to_numpy(dtype=float) for c in ("port", "bench", "turnover"))
                    nh = np.nan_to_num(sub["n_hold"].to_numpy(dtype=float))
                    held = nh > 0
                    gross = np.where(held, port - bench, 0.0)
                    net = np.where(held, port - tr["roundtrip_cost"] * np.nan_to_num(tau, nan=1.0) - bench, 0.0)
                    stress = np.where(held, port - tr["stress_cost"] * np.nan_to_num(tau, nan=1.0) - bench, 0.0)
                    gross[~np.isfinite(gross)] = 0.0
                    net[~np.isfinite(net)] = 0.0
                    stress[~np.isfinite(stress)] = 0.0
                    lo, hi = block_ci(net, max(ts["rc_block"], 2 * h), ts["n_boot"], 0.10, seed=h)
                    r.update({"ann_gross": ann_excess(gross, h), "ann_net": ann_excess(net, h),
                              "ann_stress": ann_excess(stress, h), "ci_lo": lo * 252 / h, "ci_hi": hi * 252 / h,
                              "turnover": np.nanmean(tau[held]) if held.any() else np.nan,
                              "blocked": np.nanmean(sub["blocked"].to_numpy(dtype=float)),
                              "delayed": np.nanmean(sub["delayed"].to_numpy(dtype=float)[held]) if held.any() else np.nan,
                              "n_hold": float(nh[held].mean()) if held.any() else 0.0,
                              "hold_frac": float(held.mean()) if len(held) else np.nan})
                out.append(r)


def primary_series(df: pd.DataFrame, is_ev: bool, valid: np.ndarray) -> np.ndarray:
    """主统计量的逐日序列：连续信号为 IC；事件类为事件超额，在真实日历上无事件（<5只）的有效日记 0。"""
    s = df[_primary(is_ev)].to_numpy(dtype=float).copy()
    if is_ev:
        s = np.where(valid & ~np.isfinite(s), 0.0, s)
    s[~valid] = np.nan
    return s


def primary_matrix(daily: dict, ctx: dict, cfg: dict, split: str) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    tbl = signal_table(cfg).set_index("signal")
    cols, keys = [], []
    for name, res in daily.items():
        for h in cfg["trade"]["horizons"]:
            m = (ctx["split"] == split) & ctx["valid"][h]
            cols.append(primary_series(res[h], bool(tbl.loc[name, "event"]), m))
            keys.append((name, h))
    X = pd.DataFrame(np.column_stack(cols), index=ctx["dates"])
    return X[(ctx["split"] == split)], keys


def market_regime(P: Panel, cfg: dict) -> pd.Series:
    """中证800 均线法（研究F同口径：年线 + 20日斜率，新环境连续 10 天才确认）；模拟数据用等权指数。"""
    code = cfg["data"].get("regime_index", "000906")
    q = Path(cfg["data"].get("qlib_dir", ""))
    path = q / "features" / f"sh{code}" / "close.day.bin"
    close = None
    if cfg.get("_real", False) and path.exists():
        cal = read_calendar(q)
        s = pd.Series(read_bin(path, len(cal)), index=cal).reindex(P.dates)
        if s.notna().mean() > 0.99:
            close = s.ffill()
    if close is None:
        r = pd.DataFrame(P.ret).where(pd.DataFrame(P.in_univ)).mean(axis=1).fillna(0).to_numpy()
        close = pd.Series(np.cumprod(1 + r), index=P.dates)
    return persist(regime_ma(close, 250, 20), 10)


def verdict_dv(P: Panel, daily: dict, ctx: dict, summary: pd.DataFrame, cfg: dict, log=print) -> dict:
    """测试前判定：显著性（BH + 同向）、Reality Check、FM 增量信息、可交易性、参数平台 → 预判等级。"""
    ts = cfg["test"]
    horizons = cfg["trade"]["horizons"]
    key = ["signal", "h"]
    disc = summary[summary.split == "discovery"].set_index(key)
    val = summary[summary.split == "validation"].set_index(key)
    v = val[["category", "event", "direction", "stat_mean", "stat_t", "stat_p", "ic_mean", "ic_t"]].copy()
    v["disc_stat_t"] = disc["stat_t"]
    v["disc_ic_mean"] = disc["ic_mean"]
    v["q"] = bh_adjust(v["stat_p"].to_numpy())
    # Reality Check（验证集主统计量）
    X, keys = primary_matrix(daily, ctx, cfg, "validation")
    se = np.array([nw_se(X.iloc[:, i].to_numpy(), max(h, ts["nw_min_lag"])) for i, (_, h) in enumerate(keys)])
    rc = reality_check(X.to_numpy(), se, ts["rc_boot"], ts["rc_block"], seed=cfg.get("seed", 20260930))
    v["rc_p"] = pd.Series(rc, index=pd.MultiIndex.from_tuples(keys, names=key))
    v["same_sign"] = np.sign(v["stat_t"]) == np.sign(v["disc_stat_t"])
    v["sig"] = (v["stat_t"].abs() > ts["t_threshold"]) & (v["q"] < ts["fdr_q"]) & v["same_sign"]
    # 参数平台
    v["plateau"] = np.nan
    fams = cfg["families"]
    for h in horizons:
        tv = {s: v.loc[(s, h), "stat_t"] for s in v.index.get_level_values(0).unique() if (s, h) in v.index}
        for fam in fams.values():
            if not all(s in tv for s in fam):
                continue
            for s, ok in plateau(tv, fam, ts["plateau_ratio"]).items():
                v.loc[(s, h), "plateau"] = float(ok)
    # 可交易性（验证集）
    for c in ("ann_gross", "ann_net", "ann_stress", "ci_lo", "ci_hi", "turnover", "blocked", "delayed", "n_hold"):
        v[c] = val[c] if c in val else np.nan
    v["avoid_only"] = v["event"] & (v["direction"] < 0)
    v["bt_ok"] = (v["ann_net"] > 0) & (v["ci_lo"] > 0) & ~v["avoid_only"]
    # FM（只对显著者）
    v["fm_t"] = np.nan
    v["fm_coef"] = np.nan
    sig_keys = list(v.index[v["sig"]])
    if sig_keys:
        log(f"FM 回归：{len(sig_keys)} 个显著的 信号×持有期")
        v = _fm_block(P, ctx, cfg, v, sig_keys, log)
    v["fm_ok"] = (v["fm_t"].abs() > ts["fm_min_t"]) & (np.sign(v["fm_t"]) == np.sign(v["stat_t"]))
    v["base_factor"] = v.index.get_level_values(0).isin(cfg["controls"]["factors"])
    plat_ok = v["plateau"].isna() | (v["plateau"] == 1)
    v["pre_grade"] = np.where(~v["sig"], "C", np.where(v["fm_ok"] & v["bt_ok"] & plat_ok, "A候选", "B"))
    # 市场环境 IC
    reg = market_regime(P, cfg).reindex(ctx["dates"]).to_numpy()
    tbl = signal_table(cfg).set_index("signal")
    reg_rows = []
    for (s, h) in v.index:
        m0 = (ctx["split"] == "validation") & ctx["valid"][h]
        prim = primary_series(daily[s][h], bool(tbl.loc[s, "event"]), m0)
        r = {"signal": s, "h": h}
        for lab in ("牛市", "震荡", "熊市"):
            x = nw_t(prim[m0 & (reg == lab)], max(h, ts["nw_min_lag"]))
            r[f"{lab}_均值"], r[f"{lab}_t"], r[f"{lab}_天数"] = x["mean"], x["t"], x["n"]
        reg_rows.append(r)
    return {"verdict": v.reset_index(), "regime": pd.DataFrame(reg_rows),
            "regime_days": pd.Series(reg[ctx["split"] == "validation"]).value_counts().to_dict()}


def _fm_block(P: Panel, ctx: dict, cfg: dict, v: pd.DataFrame, sig_keys: list, log) -> pd.DataFrame:
    rows = ctx["rows"]
    ctrl_names = cfg["controls"]["factors"]
    P.drop_cache()
    ctrls = {c: I.compute(c, P)[rows] for c in ctrl_names}
    sec = pd.Series(P.sector).fillna("")
    cats = sorted(x for x in sec.unique() if x)
    code = sec.map({c: i + 1 for i, c in enumerate(cats)}).fillna(0).astype(int).to_numpy()
    if not cfg["controls"].get("industry", True):
        code = np.zeros_like(code)
    tier = ctx["tier"] if cfg["controls"].get("size_tiers", True) else np.zeros_like(ctx["tier"])
    by_h: dict[int, list[str]] = {}
    for s, h in sig_keys:
        by_h.setdefault(h, []).append(s)
    for h, sigs in by_h.items():
        Y = ctx["Y"][h]
        cu = control_ranks(ctrls, ctx["E"], Y)
        mask = (ctx["split"] == "validation") & ctx["valid"][h]
        for s in sigs:
            arr = ctrls[s] if s in ctrls else I.compute(s, P)[rows]
            beta = fama_macbeth(arr, Y, ctx["E"], cu, tier, code, mask, exclude=s)
            r = fm_summary(beta, h, cfg["test"]["nw_min_lag"])
            v.loc[(s, h), "fm_t"] = r["fm_t"]
            v.loc[(s, h), "fm_coef"] = r["fm_coef"]
            log(f"  FM h={h} {s}: t={r['fm_t']:.2f}")
        del cu
        P.drop_cache()
    return v
