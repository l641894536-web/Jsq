"""按资产类别研究：每类一套策略库，同类标的合并检验。

和逐标的回测的区别：
  * 每类只测适合它的策略（CLASS_LIB），参数 + 出场方式 + 行情过滤 在全类所有标的上共用一套
  * 同类标的的交易合并统计：样本更多，也避免为单个标的量身拟合
  * 滚动样本外按日历时间切分；每段只用此前的交易挑配置，按 R 倍数的 t 值打分（期望为正且稳定）
  * 核心指标是扣费后每笔期望收益（基点 和 R 倍数）与盈亏比，而不是胜率
    R 倍数 = 单笔收益 / 开仓时 1 小时 ATR 占价格的比例，把不同波动的标的放在同一尺度
  * 持仓时间曲线：信号出现后持有 1 小时 ~ 7 天，各持有期的平均扣费收益，找最合适的持有时间
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest as bt
from .cross import group_of
from .regime import FILTERS, regimes
from .strategies import STRATEGIES

CLASS_LIB = {
    "加密": ["funding_fade", "funding_follow", "premium_fade", "oi_flow", "squeeze_fade", "crowd_fade",
           "smart_follow", "rel_revert", "ema_cross", "donchian", "tsmom", "bb_revert", "shock"],
    "美股/ETF": ["gap_trade", "opening_range", "offhours_fade", "peer_lead", "rel_revert", "shock",
               "ema_cross", "tsmom", "bb_revert", "crowd_fade"],
    "贵金属": ["ema_cross", "donchian", "tsmom", "macd_trend", "bb_revert", "rsi_revert", "rel_revert",
            "session_break", "shock", "depth_imbalance"],
    "能源": ["ema_cross", "donchian", "tsmom", "macd_trend", "trend_funding", "bb_revert", "session_break",
           "eia_trade", "shock"],
}

# 出场方式：ATR 为 1 小时 ATR(14)。h* = 4ATR 止损 + 最长持有 * 小时
CLASS_EXITS = {
    "sig": dict(),
    "sl2tp6": dict(stop_atr=2.0, tp_atr=6.0),
    "trail4": dict(trail_atr=4.0),
    "h12": dict(stop_atr=4.0, max_hold_h=12),
    "h24": dict(stop_atr=4.0, max_hold_h=24),
    "h48": dict(stop_atr=4.0, max_hold_h=48),
    "h96": dict(stop_atr=4.0, max_hold_h=96),
    "h168": dict(stop_atr=4.0, max_hold_h=168),
}
EXIT_CN = {"sig": "信号进出", "sl2tp6": "2ATR止损/6ATR止盈", "trail4": "4ATR移动止损", "h12": "最长12h",
           "h24": "最长24h", "h48": "最长48h", "h96": "最长4天", "h168": "最长7天"}
DECAY_H = [1, 2, 4, 8, 12, 24, 48, 72, 120, 168]
MIN_TRADES = 30


@dataclass
class ClassResult:
    group: str
    oos: pd.DataFrame        # 每个策略的样本外汇总
    regime: pd.DataFrame     # 样本外交易按开仓时行情状态拆分
    decay: pd.DataFrame      # 持仓时间曲线
    folds: pd.DataFrame
    curves: pd.DataFrame     # 样本外累计收益（基点，按出场时间）
    best: dict


def trade_stats(t: pd.DataFrame) -> dict:
    n = len(t)
    if n == 0:
        return {"trades": 0}
    r = t["ret"].to_numpy()
    R = t["R"].to_numpy()
    win, loss = r[r > 0], r[r <= 0]
    aw = win.mean() if len(win) else 0.0
    al = loss.mean() if len(loss) else 0.0
    by_sym = t.groupby("symbol")["ret"].sum()
    return {
        "trades": n, "symbols": int(t["symbol"].nunique()),
        "win_rate": len(win) / n,
        "avg_win_bps": aw * 1e4, "avg_loss_bps": al * 1e4,
        "payoff": aw / -al if al < 0 else np.inf,
        "exp_bps": r.mean() * 1e4, "exp_R": R.mean(),
        "profit_factor": win.sum() / -loss.sum() if loss.sum() < 0 else np.inf,
        "t_R": R.mean() / R.std(ddof=1) * np.sqrt(n) if n > 2 and R.std(ddof=1) > 0 else 0.0,
        "avg_hold_h": t["hold_h"].mean(),
        "sym_pos": float((by_sym > 0).mean()),
        "long_share": float((t["dir"] == 1).mean()),
    }


def _score(t: pd.DataFrame) -> float:
    if len(t) < MIN_TRADES:
        return -np.inf
    R = t["R"].to_numpy()
    sd = R.std(ddof=1)
    return R.mean() / sd * np.sqrt(len(R)) if sd > 0 else -np.inf


def decay_curve(df: pd.DataFrame, sig: np.ndarray, atr: np.ndarray, cost: float, allow=None) -> dict:
    """信号新出现（从 0/反向 变成 ±1）后，从下一根开盘起持有 h 小时的平均扣费收益。"""
    s = np.asarray(sig)
    prev = np.concatenate([[0], s[:-1]])
    ev = np.flatnonzero((s != 0) & (s != prev))
    if allow is not None:
        ev = ev[allow[ev]]
    o = df["open"].to_numpy()
    bh = df.attrs.get("bar_hours", 1.0)
    out = {}
    for h in DECAY_H:
        k = max(1, int(round(h / bh)))
        e = ev[ev + 1 + k < len(o)]
        if not len(e):
            continue
        r = s[e] * (o[e + 1 + k] / o[e + 1] - 1) - 2 * cost
        R = r / (atr[e] / o[e + 1])
        out[h] = (r, R)
    return out


def run_class(frames: list[pd.DataFrame], group: str, cost: float, folds: int = 3,
              initial_frac: float = 0.4, strategies: list[str] | None = None, progress=None,
              exits: dict | None = None) -> ClassResult:
    exits = exits or CLASS_EXITS
    names = [s for s in (strategies or CLASS_LIB[group]) if s in STRATEGIES]
    preps = {f.attrs["symbol"]: (f, bt.Prepared.from_frame(f), regimes(f)) for f in frames}
    t0 = min(f.index[0] for f in frames)
    t1 = max(f.index[-1] for f in frames)
    cuts = [t0 + (t1 - t0) * (initial_frac + (1 - initial_frac) * k / folds) for k in range(folds + 1)]
    oos_rows, reg_rows, decay_rows, fold_rows, curve_rows, best = [], [], [], [], [], {}
    auto_picks: list[list] = [[] for _ in range(folds)]

    for name in names:
        st = STRATEGIES[name]
        cands = []  # (params, exit, filter, trades)
        sigs = {}
        for params in st.param_sets():
            key = json.dumps(params, ensure_ascii=False)
            per_exit: dict[str, list] = {e: [] for e in exits}
            for sym, (f, p, reg) in preps.items():
                if not st.available(f):
                    continue
                sig = st.signal(f, params)
                sigs[(key, sym)] = sig
                for ename, ex in exits.items():
                    res = bt.run(p, sig, cost, **ex)
                    t = res.trades
                    if not len(t):
                        continue
                    ei = t["entry_i"].to_numpy()
                    atr_pct = p.atr[ei - 1] / t["entry_px"].to_numpy()
                    per_exit[ename].append(t.assign(symbol=sym, R=t["ret"].to_numpy() / atr_pct,
                                                    regime=reg.to_numpy()[ei - 1]))
            for ename, parts in per_exit.items():
                if not parts:
                    continue
                allt = pd.concat(parts, ignore_index=True).dropna(subset=["R"])
                for fname, allowed in FILTERS.items():
                    tt = allt if allowed is None else allt[allt["regime"].isin(allowed)]
                    cands.append((params, ename, fname, tt))
        if not cands:
            continue
        # 滚动样本外：每段用此前（已平仓）的交易挑配置
        picked, oos_parts = [], []
        for k in range(folds):
            lo, hi = cuts[k], cuts[k + 1]
            best_c, best_s = None, -np.inf
            for c in cands:
                tr = c[3]
                s = _score(tr[tr["exit_time"] < lo])
                if s > best_s:
                    best_c, best_s = c, s
            if best_c is None:
                fold_rows.append({"group": group, "strategy": name, "fold": k + 1, "params": "", "exit": "",
                                  "filter": "", "is_t": np.nan, "oos_trades": 0, "oos_exp_bps": np.nan})
                continue
            tr = best_c[3]
            part = tr[(tr["entry_time"] >= lo) & (tr["entry_time"] < hi)]
            oos_parts.append(part)
            picked.append(best_c)
            auto_picks[k].append((best_s, name, best_c, part))
            fold_rows.append({"group": group, "strategy": name, "fold": k + 1,
                              "params": json.dumps(best_c[0], ensure_ascii=False), "exit": best_c[1],
                              "filter": best_c[2], "is_t": best_s, "oos_trades": len(part),
                              "oos_exp_bps": part["ret"].mean() * 1e4 if len(part) else np.nan})
        oos = pd.concat(oos_parts, ignore_index=True) if oos_parts else pd.DataFrame()
        stats = trade_stats(oos) if len(oos) else {"trades": 0}
        common = pd.Series([f"{c[1]}|{c[2]}" for c in picked]).mode()
        oos_rows.append({"group": group, "strategy": name, "label": st.label,
                         "exit_filter": common.iloc[0] if len(common) else "", **stats})
        if len(oos):
            for rg, g in oos.groupby("regime"):
                reg_rows.append({"group": group, "strategy": name, "regime": rg, **trade_stats(g)})
            cr = oos.sort_values("exit_time")
            curve_rows.append(pd.DataFrame({"group": group, "strategy": name, "time": cr["exit_time"].values,
                                            "cum_bps": (cr["ret"].cumsum() * 1e4).values}))
        # 全样本最佳配置：给实盘用 + 画持仓时间曲线
        full = max(cands, key=lambda c: _score(c[3]))
        if _score(full[3]) > -np.inf:
            best[name] = {"params": full[0], "exit": full[1], "filter": full[2], "full_t": _score(full[3]),
                          "oos_exp_bps": stats.get("exp_bps"), "oos_trades": stats.get("trades")}
            key = json.dumps(full[0], ensure_ascii=False)
            acc: dict[int, list] = {h: [] for h in DECAY_H}
            for sym, (f, p, reg) in preps.items():
                sig = sigs.get((key, sym))
                if sig is None:
                    continue
                allowed = FILTERS[full[2]]
                allow = None if allowed is None else reg.isin(allowed).to_numpy()
                for h, (r, R) in decay_curve(f, sig, p.atr, cost, allow).items():
                    acc[h].append((r, R))
            for h, lst in acc.items():
                if not lst:
                    continue
                r = np.concatenate([x[0] for x in lst])
                R = np.concatenate([x[1] for x in lst])
                R = R[np.isfinite(R)]
                decay_rows.append({"group": group, "strategy": name, "horizon_h": h, "events": len(r),
                                   "exp_bps": r.mean() * 1e4, "exp_R": R.mean() if len(R) else np.nan,
                                   "win_rate": (r > 0).mean(),
                                   "t": r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if len(r) > 2 else np.nan})
        if progress:
            progress(group, name)

    # AUTO：每段在本类所有策略的训练期冠军中再选一个
    parts = []
    for k in range(folds):
        if auto_picks[k]:
            s, name, c, part = max(auto_picks[k], key=lambda x: x[0])
            parts.append(part.assign(strategy=name))
            fold_rows.append({"group": group, "strategy": "AUTO", "fold": k + 1, "picked": name,
                              "params": json.dumps(c[0], ensure_ascii=False), "exit": c[1], "filter": c[2],
                              "is_t": s, "oos_trades": len(part),
                              "oos_exp_bps": part["ret"].mean() * 1e4 if len(part) else np.nan})
    if parts:
        oos = pd.concat(parts, ignore_index=True)
        oos_rows.append({"group": group, "strategy": "AUTO", "label": "自动选优(每段选训练期最佳)",
                         "exit_filter": "", **trade_stats(oos)})
        cr = oos.sort_values("exit_time")
        curve_rows.append(pd.DataFrame({"group": group, "strategy": "AUTO", "time": cr["exit_time"].values,
                                        "cum_bps": (cr["ret"].cumsum() * 1e4).values}))
    meta = {"oos_start": str(cuts[0])[:10], "end": str(t1)[:10], "symbols": [f.attrs["symbol"] for f in frames]}
    best["_meta"] = meta
    return ClassResult(group, pd.DataFrame(oos_rows), pd.DataFrame(reg_rows), pd.DataFrame(decay_rows),
                       pd.DataFrame(fold_rows),
                       pd.concat(curve_rows, ignore_index=True) if curve_rows else pd.DataFrame(), best)


def groups_for(symbols: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in symbols:
        out.setdefault(group_of(s), []).append(s)
    return out


def _run_group(group, symbols, interval, data_dir, cost, folds, strategies, exits=None):
    from pathlib import Path

    from .data import load_frame
    frames = []
    for s in symbols:
        try:
            f = load_frame(s, interval, Path(data_dir))
            if len(f) >= 500:
                frames.append(f)
        except FileNotFoundError:
            pass
    if not frames:
        return None
    return run_class(frames, group, cost, folds=folds, strategies=strategies, exits=exits)


def run_all(symbols, interval, data_dir, cost, out_dir, folds=3, strategies=None, jobs=4, exits=None):
    import logging
    from concurrent.futures import ProcessPoolExecutor
    log = logging.getLogger(__name__)
    gs = groups_for(symbols)
    results = []
    with ProcessPoolExecutor(max_workers=min(jobs, len(gs))) as ex:
        futs = {ex.submit(_run_group, g, syms, interval, str(data_dir), cost, folds,
                          [s for s in strategies if s in CLASS_LIB[g]] if strategies else None, exits): g
                for g, syms in gs.items() if not strategies or any(s in CLASS_LIB[g] for s in strategies)}
        for fu in futs:
            r = fu.result()
            if r is not None:
                results.append(r)
                log.info("完成 %s", futs[fu])
    for attr, fname in (("oos", "class_oos.csv"), ("regime", "class_regime.csv"), ("decay", "class_decay.csv"),
                        ("folds", "class_folds.csv")):
        pd.concat([getattr(r, attr) for r in results], ignore_index=True).to_csv(out_dir / fname, index=False)
    cv = [r.curves for r in results if len(r.curves)]
    if cv:
        pd.concat(cv, ignore_index=True).to_csv(out_dir / "class_curves.csv.gz", index=False, compression="gzip")
    (out_dir / "class_best.json").write_text(json.dumps({r.group: r.best for r in results}, ensure_ascii=False,
                                                       indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return results
