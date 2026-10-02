"""参数网格 + 滚动样本外（walk-forward）评估。

为什么要样本外：几百组参数里挑回测最好的那组，几乎一定是过拟合。这里的做法是
  1. 数据按时间切成：初始训练段 + K 个样本外(OOS)段
  2. 每个 OOS 段开始前，只用它之前的全部数据挑参数（按夏普，交易数不足的不参与）
  3. 用挑出的参数跑这个 OOS 段，把 K 段拼起来就是“如果当时这样做，实际会得到”的结果
报告里的胜率/收益/夏普默认都是 OOS 结果；全样本最优的数字只作参考。
另外 AUTO 行表示“每段都在所有策略里挑训练期最好的那个”，用来检验选策略本身的过拟合。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import backtest as bt
from .config import BacktestConfig
from .strategies import Strategy

NEG_INF = float("-inf")


@dataclass
class Candidate:
    score: float
    strategy: str
    params: dict
    exit: str
    res: bt.Result = field(repr=False)
    br: np.ndarray = field(repr=False)


@dataclass
class SymbolResult:
    symbol: str
    grid: pd.DataFrame
    oos: pd.DataFrame
    folds: pd.DataFrame
    curves: dict
    best: dict
    oos_start: str = ""


def fold_edges(n: int, cfg: BacktestConfig) -> list[int]:
    e0 = int(n * cfg.initial_train_frac)
    return [int(x) for x in np.linspace(e0, n, cfg.folds + 1).round()]


def _score(m: dict, min_trades: int) -> float:
    if m["trades"] < min_trades or not np.isfinite(m["sharpe"]):
        return NEG_INF
    return m["sharpe"]


def _assemble(name: str, picks: list[Candidate | None], edges: list[int], p: bt.Prepared):
    """把各 OOS 段选中的参数结果拼成一条样本外曲线。"""
    brs, poss, trades, fold_rows = [], [], [], []
    for k, cand in enumerate(picks):
        lo, hi = edges[k], edges[k + 1]
        if cand is None or cand.score == NEG_INF:
            brs.append(np.zeros(hi - lo))
            poss.append(np.zeros(hi - lo, np.int8))
            fold_rows.append({"fold": k + 1, "strategy": name, "params": "", "exit": "", "is_sharpe": np.nan,
                              "oos_return": 0.0, "oos_trades": 0})
            continue
        br = cand.br[lo:hi]
        t = cand.res.trades
        if len(t):
            ei = t["entry_i"].to_numpy()
            t = t[(ei >= lo) & (ei < hi)]
        brs.append(br)
        poss.append(cand.res.position[lo:hi])
        trades.append(t.assign(strategy=cand.strategy))
        fold_rows.append({"fold": k + 1, "strategy": name,
                          "picked": cand.strategy if cand.strategy != name else "",
                          "params": json.dumps(cand.params, ensure_ascii=False), "exit": cand.exit,
                          "is_sharpe": cand.score, "oos_return": float(np.prod(1 + br) - 1),
                          "oos_trades": len(t)})
    br = np.concatenate(brs) if brs else np.zeros(0)
    pos = np.concatenate(poss) if poss else np.zeros(0, np.int8)
    tr = pd.concat(trades, ignore_index=True) if trades else bt.empty_trades()
    m = bt.metrics(br, pos, tr, p.bar_hours)
    fr = pd.DataFrame(fold_rows)
    m["folds_positive"] = int((fr["oos_return"] > 0).sum())
    m["folds"] = len(fr)
    curve = pd.Series(np.cumprod(1 + br), index=p.index[edges[0]:edges[-1]], name=name)
    return m, fr, curve, tr


def evaluate_symbol(df: pd.DataFrame, cfg: BacktestConfig, strategies: list[Strategy],
                    progress=None) -> SymbolResult:
    symbol = df.attrs.get("symbol", "?")
    p = bt.Prepared.from_frame(df, cfg.atr_period)
    n = len(df)
    edges = fold_edges(n, cfg)
    grid_rows, oos_rows, fold_frames, curves, best = [], [], [], {}, {}
    all_picks: list[list[Candidate | None]] = []

    for strat in strategies:
        if not strat.available(df):
            continue
        picks: list[Candidate | None] = [None] * cfg.folds
        live: Candidate | None = None
        for params in strat.param_sets():
            sig = strat.signal(df, params)
            for ename, ex in cfg.exit_profiles.items():
                res = bt.run(p, sig, cfg.cost, **ex)
                br = bt.bar_returns(res.equity)
                full = bt.metrics(br, res.position, res.trades, p.bar_hours)
                oos_part = bt.window_metrics(res, edges[0], n, p.bar_hours, br)
                grid_rows.append({"symbol": symbol, "strategy": strat.name, "label": strat.label,
                                  "params": json.dumps(params, ensure_ascii=False), "exit": ename,
                                  **full, "oos_period_sharpe": oos_part["sharpe"],
                                  "oos_period_return": oos_part["total_return"]})
                for k in range(cfg.folds):
                    m = bt.window_metrics(res, 0, edges[k], p.bar_hours, br)
                    s = _score(m, cfg.min_trades)
                    if s > NEG_INF and (picks[k] is None or s > picks[k].score):
                        picks[k] = Candidate(s, strat.name, params, ename, res, br)
                s = _score(full, cfg.min_trades)
                if s > NEG_INF and (live is None or s > live.score):
                    live = Candidate(s, strat.name, params, ename, res, br)
        m, fr, curve, _ = _assemble(strat.name, picks, edges, p)
        oos_rows.append({"symbol": symbol, "strategy": strat.name, "label": strat.label, "group": strat.group,
                         **m})
        fold_frames.append(fr.assign(symbol=symbol))
        curves[strat.name] = curve
        if live is not None:
            best[strat.name] = {"params": live.params, "exit": live.exit, "full_sharpe": live.score,
                                "oos_sharpe": m["sharpe"], "oos_win_rate": m["win_rate"],
                                "oos_trades": m["trades"], "oos_return": m["total_return"]}
        all_picks.append(picks)
        if progress:
            progress(symbol, strat.name)

    # AUTO：每段在所有策略的训练期冠军里再挑一个
    if all_picks:
        auto = []
        for k in range(cfg.folds):
            cands = [pk[k] for pk in all_picks if pk[k] is not None]
            auto.append(max(cands, key=lambda c: c.score) if cands else None)
        m, fr, curve, _ = _assemble("AUTO", auto, edges, p)
        oos_rows.append({"symbol": symbol, "strategy": "AUTO", "label": "自动选优(各段选训练期最佳策略)",
                         "group": "基准", **m})
        fold_frames.append(fr.assign(symbol=symbol))
        curves["AUTO"] = curve

    # 买入持有基准（同一 OOS 区间）
    bh_eq = p.c[edges[0]:] / p.o[edges[0]]
    bh_br = bt.bar_returns(bh_eq)
    m = bt.metrics(bh_br, np.ones(len(bh_br), np.int8), bt.empty_trades(), p.bar_hours)
    m.update(trades=1, folds_positive=np.nan, folds=cfg.folds)
    oos_rows.append({"symbol": symbol, "strategy": "buy_hold", "label": "买入持有", "group": "基准", **m})
    curves["buy_hold"] = pd.Series(bh_eq, index=p.index[edges[0]:], name="buy_hold")

    return SymbolResult(symbol, pd.DataFrame(grid_rows), pd.DataFrame(oos_rows),
                        pd.concat(fold_frames, ignore_index=True) if fold_frames else pd.DataFrame(),
                        curves, best, oos_start=str(p.index[edges[0]]) if n else "")
