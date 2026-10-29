"""先看方向、再谈出场：按“整条路比随机好”挑参数，做滚动样本外检验，用来筛新指标。

每个候选（策略 × 参数 × 行情过滤）的每次开仓算一个路径得分：
  信号方向的（一路顺 − 先顺后大逆 − 直接逆） − 同一时刻反方向的同一得分，取值 −2..2；随机猜方向时平均为 0。
时间切段与 classlab 相同：前 40% 只用来挑，后 60% 分 3 段；每段开始前只用此前已经走完整条路
（开仓 + 观察窗口都在段前）的开仓挑得分 t 值最高的配置，再看这一段的路径分布、
止损 2 份 / 止盈 3 份的扣费收益和不设止损持有到窗口结束的收益。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import backtest as bt
from . import excursion as ex
from .regime import FILTERS, regimes
from .strategies import STRATEGIES

NEW_BREAKOUTS = ["bb_break", "keltner_break", "squeeze_break"]


def _event_table(f: pd.DataFrame, p, reg: np.ndarray, sg: np.ndarray, H: int, r_atr: float, cost: float) -> pd.DataFrame:
    prev = np.concatenate([[0], sg[:-1]])
    ev = np.flatnonzero((sg != 0) & (sg != prev))
    ev, entry, hi, lo, endp = ex.hourly_paths(p, ev, H)
    r = r_atr * p.atr[ev]
    ok = np.isfinite(r) & (r > 0)
    if not ok.any():
        return pd.DataFrame()
    ev, entry, hi, lo, endp, r = ev[ok], entry[ok], hi[ok], lo[ok], endp[ok], r[ok]
    side = sg[ev].astype(float)
    sig, opp = ex.touches(hi, lo, entry, side, r, endp), ex.touches(hi, lo, entry, -side, r, endp)
    fs, fo = ex.path_flags(sig), ex.path_flags(opp)
    cost_r = 2 * cost * entry / r
    score = lambda f_: f_["trend"].astype(float) - f_["fake"] - f_["direct"]
    return pd.DataFrame({"when": f.index[ev + 1], "regime": reg[ev], "score": score(fs) - score(fo),
                         "trend": fs["trend"], "trend_b": (fs["trend"].astype(float) + fo["trend"]) / 2,
                         "fake": fs["fake"], "fake_b": (fs["fake"].astype(float) + fo["fake"]) / 2,
                         "direct": fs["direct"], "direct_b": (fs["direct"].astype(float) + fo["direct"]) / 2,
                         "bracket": ex.outcome(sig, 3.0, 2.0) - cost_r, "hold": sig["end"].to_numpy() - cost_r})


def screen_group(frames: dict[str, pd.DataFrame], group: str, strategies: list[str], r_atr: float = 2.0,
                 horizon_h: int = 72, cost: float = 0.0007, folds: int = 3, initial_frac: float = 0.4,
                 min_events: int = 30) -> pd.DataFrame:
    preps = {s: (f, bt.Prepared.from_frame(f), regimes(f).to_numpy()) for s, f in frames.items()}
    t0 = min(f.index[0] for f in frames.values())
    t1 = max(f.index[-1] for f in frames.values())
    cuts = [t0 + (t1 - t0) * (initial_frac + (1 - initial_frac) * k / folds) for k in range(folds + 1)]
    H = max(1, int(round(horizon_h / float(next(iter(frames.values())).attrs.get("bar_hours", 1.0)))))
    look = pd.Timedelta(hours=horizon_h)
    rows = []
    for name in strategies:
        st = STRATEGIES.get(name)
        if st is None:
            continue
        cands = []
        for params in st.param_sets():
            per = []
            for s, (f, p, reg) in preps.items():
                if not st.available(f):
                    continue
                t = _event_table(f, p, reg, st.signal(f, params), H, r_atr, cost)
                if len(t):
                    per.append(t.assign(symbol=s))
            if not per:
                continue
            allev = pd.concat(per, ignore_index=True)
            for fname, allowed in FILTERS.items():
                cands.append((params, fname, allev if allowed is None else allev[allev["regime"].isin(allowed)]))
        parts, picks = [], []
        for k in range(folds):
            lo_t, hi_t = cuts[k], cuts[k + 1]
            best, best_t = None, -np.inf
            for c in cands:
                tr = c[2][c[2]["when"] + look < lo_t]
                if len(tr) < min_events:
                    continue
                tt = ex._t(tr["score"].to_numpy())
                if np.isfinite(tt) and tt > best_t:
                    best, best_t = c, tt
            if best is None:
                continue
            part = best[2][(best[2]["when"] >= lo_t) & (best[2]["when"] < hi_t)]
            parts.append(part)
            picks.append({"fold": k + 1, "params": best[0], "filter": best[1], "is_t": round(float(best_t), 2),
                          "oos_n": len(part)})
        if not parts:
            continue
        o = pd.concat(parts, ignore_index=True)
        if len(o) < 10:
            continue
        mid = o["when"].sort_values().iloc[len(o) // 2]
        a, b = o[o["when"] < mid], o[o["when"] >= mid]
        rows.append({"group": group, "strategy": name, "label": st.label, "n": len(o), "path_t": ex._t(o["score"].to_numpy()),
                     **{c: float(o[c].mean()) for c in ("trend", "trend_b", "fake", "fake_b", "direct", "direct_b")},
                     "bracket": float(o["bracket"].mean()), "bracket_t": ex._t(o["bracket"].to_numpy()),
                     "bracket_1": float(a["bracket"].mean()), "bracket_2": float(b["bracket"].mean()),
                     "hold": float(o["hold"].mean()), "score_1": float(a["score"].mean()), "score_2": float(b["score"].mean()),
                     "sym_pos": float((o.groupby("symbol")["score"].mean() > 0).mean()),
                     "picks": json.dumps(picks, ensure_ascii=False)})
    return pd.DataFrame(rows)


def screen_all(symbols: list[str], data_dir, interval: str = "1h", strategies: dict[str, list[str]] | None = None,
               **kw) -> pd.DataFrame:
    """每类：classlab 的策略库 + 新的突破类候选。"""
    from pathlib import Path

    from .classlab import CLASS_LIB, groups_for
    from .data import load_frame
    out = []
    for group, syms in groups_for(symbols).items():
        frames = {}
        for s in syms:
            try:
                f = load_frame(s, interval, Path(data_dir))
            except FileNotFoundError:
                continue
            if len(f) >= 500:
                frames[s] = f
        if not frames:
            continue
        names = (strategies or {}).get(group) or list(dict.fromkeys(CLASS_LIB.get(group, []) + NEW_BREAKOUTS))
        out.append(screen_group(frames, group, names, **kw))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
