"""用回测选出的参数计算各标的当前的多空信号。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import indicators as ind
from .config import EXIT_PROFILES
from .data import load_frame
from .strategies import STRATEGIES

SIDE = {1: "做多", -1: "做空", 0: "观望"}


def current_signals(run_dir: Path, data_dir: Path, interval: str, symbols: list[str] | None = None,
                    top: int = 3, min_oos_sharpe: float = 0.0, min_oos_trades: int = 15) -> pd.DataFrame:
    best = json.loads((Path(run_dir) / "best_params.json").read_text())
    rows = []
    for sym, strategies in best.items():
        if symbols and sym not in symbols:
            continue
        ranked = sorted(
            ((k, v) for k, v in strategies.items()
             if (v.get("oos_sharpe") or -1) > min_oos_sharpe and (v.get("oos_trades") or 0) >= min_oos_trades),
            key=lambda kv: -kv[1]["oos_sharpe"])[:top]
        if not ranked:
            continue
        df = load_frame(sym, interval, data_dir)
        a = float(ind.atr(df, 14).iloc[-1])
        last = df.iloc[-1]
        for name, b in ranked:
            sig = STRATEGIES[name].signal(df, b["params"])
            cur = int(sig[-1])
            chg = np.flatnonzero(sig != cur)
            since = df.index[chg[-1] + 1] if len(chg) else df.index[0]
            ex = EXIT_PROFILES.get(b["exit"], {})
            px = float(last["close"])
            stop = px - cur * ex["stop_atr"] * a if cur and ex.get("stop_atr") else np.nan
            if cur and ex.get("trail_atr"):
                stop = px - cur * ex["trail_atr"] * a
            tp = px + cur * ex["tp_atr"] * a if cur and ex.get("tp_atr") else np.nan
            rows.append({
                "symbol": sym, "strategy": name, "label": STRATEGIES[name].label,
                "signal": SIDE[cur], "since": since.strftime("%m-%d %H:%M"),
                "close": px, "stop_ref": stop, "tp_ref": tp, "max_hold_h": ex.get("max_hold_h", ""),
                "funding_ann": float(last["funding_ann"]) if pd.notna(last["funding_ann"]) else np.nan,
                "oos_sharpe": b["oos_sharpe"], "oos_win_rate": b["oos_win_rate"], "oos_trades": b["oos_trades"],
                "params": json.dumps(b["params"], ensure_ascii=False), "exit": b["exit"],
                "bar_time": df.index[-1].strftime("%Y-%m-%d %H:%M"),
            })
    return pd.DataFrame(rows)
