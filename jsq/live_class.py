"""按资产类别的实时信号：用 classlab 选出的配置（参数 + 出场方式 + 行情过滤）计算各标的当前状态。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from .classlab import CLASS_EXITS, EXIT_CN, groups_for
from .regime import FILTER_CN, FILTERS, regimes
from .strategies import STRATEGIES


def latest_class_dir(base: Path) -> Path:
    dirs = sorted((d for d in Path(base).iterdir() if (d / "class_best.json").exists()), reverse=True)
    if not dirs:
        raise FileNotFoundError("还没有分类研究结果，请先运行 python -m jsq classlab")
    return dirs[0]


def gate(sig: np.ndarray, allow: np.ndarray) -> np.ndarray:
    """只允许在指定行情下开新仓；信号在不允许的行情中出现，则这一段信号整段放弃（与 classlab 统计口径一致）。"""
    out = np.zeros(len(sig), dtype=np.int8)
    prev, state = 0, 0
    for i, s in enumerate(sig.tolist()):
        if s != prev:
            state = s if (s != 0 and allow[i]) else 0
        out[i] = state
        prev = s
    return out


def pick_configs(best: dict, min_exp_bps: float = 0.0, min_trades: int = 30, only: list[str] | None = None):
    for group, d in best.items():
        for name, b in d.items():
            if name.startswith("_"):
                continue
            if only and name not in only:
                continue
            if not only and ((b.get("oos_exp_bps") or -1) <= min_exp_bps or (b.get("oos_trades") or 0) < min_trades):
                continue
            yield group, name, b


def class_signals(run_dir: Path, frames: dict[str, pd.DataFrame], cost: float, only: list[str] | None = None,
                  min_exp_bps: float = 0.0) -> pd.DataFrame:
    best = json.loads((Path(run_dir) / "class_best.json").read_text())
    oos = pd.read_csv(Path(run_dir) / "class_oos.csv")
    rows = []
    by_group = groups_for(list(frames))
    for group, name, b in pick_configs(best, min_exp_bps, only=only):
        st = STRATEGIES[name]
        o = oos[(oos["group"] == group) & (oos["strategy"] == name)]
        o = o.iloc[0] if len(o) else None
        ex = CLASS_EXITS[b["exit"]]
        for sym in by_group.get(group, []):
            df = frames[sym]
            if not st.available(df):
                continue
            reg = regimes(df)
            allowed = FILTERS[b["filter"]]
            allow = np.ones(len(df), bool) if allowed is None else reg.isin(allowed).to_numpy()
            raw = st.signal(df, b["params"])
            sig = gate(raw, allow)
            p = bt.Prepared.from_frame(df)
            res = bt.run(p, sig, cost, **ex)
            pos = int(res.position[-1])
            last = float(df["close"].iloc[-1])
            row = {"group": group, "symbol": sym, "strategy": name, "label": st.label,
                   "bar_time": df.index[-1].strftime("%Y-%m-%d %H:%M"), "close": last,
                   "regime": reg.iloc[-1], "filter": FILTER_CN[b["filter"]], "exit": EXIT_CN[b["exit"]],
                   "raw_signal": int(raw[-1]), "position": pos,
                   "oos_exp_bps": None if o is None else o["exp_bps"],
                   "oos_win_rate": None if o is None else o["win_rate"],
                   "oos_payoff": None if o is None else o["payoff"],
                   "params": json.dumps(b["params"], ensure_ascii=False)}
            if pos != 0:
                # 当前持仓 = 最后一笔“回测结束”平仓的交易
                t = res.trades.iloc[-1]
                epx = float(t["entry_px"])
                a = p.atr[int(t["entry_i"]) - 1]
                stop = epx - pos * ex["stop_atr"] * a if ex.get("stop_atr") else np.nan
                tp = epx + pos * ex["tp_atr"] * a if ex.get("tp_atr") else np.nan
                if ex.get("trail_atr"):
                    seg = df.iloc[int(t["entry_i"]):]
                    best_px = seg["high"].max() if pos == 1 else seg["low"].min()
                    stop = best_px - pos * ex["trail_atr"] * a
                row.update(entry_time=t["entry_time"].strftime("%Y-%m-%d %H:%M"), entry_px=epx,
                           pnl_pct=pos * (last / epx - 1) * 100, stop=stop, take_profit=tp,
                           held_h=(len(df) - int(t["entry_i"])) * p.bar_hours,
                           max_hold_h=ex.get("max_hold_h", np.nan))
            rows.append(row)
    return pd.DataFrame(rows)
