"""把 数据 -> 预测力分析 -> 回测 -> 报告 串起来，结果写到 results/<时间戳>/。"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import predictive_power, seasonality
from .config import RESULTS_DIR, BacktestConfig
from .data import coverage, load_frame
from .optimize import evaluate_symbol
from .strategies import get_strategies

log = logging.getLogger(__name__)


def new_results_dir(base: Path = RESULTS_DIR) -> Path:
    d = Path(base) / time.strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    (Path(base) / "LATEST").write_text(d.name)
    return d


def latest_results_dir(base: Path = RESULTS_DIR) -> Path:
    f = Path(base) / "LATEST"
    if not f.exists():
        raise FileNotFoundError("还没有回测结果，请先运行 backtest 或 run")
    return Path(base) / f.read_text().strip()


def _process(symbol, interval, data_dir, start, end, cfg, strategy_names, do_backtest):
    df = load_frame(symbol, interval, Path(data_dir), start, end)
    if len(df) < 500:
        raise ValueError(f"{symbol} 只有 {len(df)} 根 K 线，样本太少")
    cov = coverage(df)
    ic = predictive_power(df)
    seas = seasonality(df)
    res = evaluate_symbol(df, cfg, get_strategies(strategy_names)) if do_backtest else None
    if res is not None:
        cov["oos_start"] = res.oos_start[:10]
    return symbol, cov, (ic, seas), res


def run_pipeline(symbols, interval, data_dir, cfg: BacktestConfig, start=None, end=None,
                 strategy_names=None, jobs=None, backtest=True, out_dir: Path | None = None) -> Path:
    out = out_dir or new_results_dir()
    jobs = jobs or max(1, min(len(symbols), (os.cpu_count() or 2) - 1))
    covs, ics, seass, oos, grids, folds, curves, best, errors = [], [], [], [], [], [], [], {}, {}
    t0 = time.time()
    args = [(s, interval, str(data_dir), start, end, cfg, strategy_names, backtest) for s in symbols]

    def collect(r):
        sym, cov, (ic, seas), res = r
        covs.append(cov)
        ics.append(ic)
        seass.append(seas)
        if res is not None:
            oos.append(res.oos)
            grids.append(res.grid)
            folds.append(res.folds)
            best[sym] = res.best
            for name, c in res.curves.items():
                curves.append(pd.DataFrame({"symbol": sym, "strategy": name, "time": c.index, "equity": c.values}))
        log.info("完成 %s（已用 %.0fs）", sym, time.time() - t0)

    if jobs > 1 and len(symbols) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(_process, *a): a[0] for a in args}
            for f in as_completed(futs):
                try:
                    collect(f.result())
                except Exception as e:  # noqa: BLE001
                    errors[futs[f]] = str(e)
                    log.error("%s 失败: %s", futs[f], e)
    else:
        for a in args:
            try:
                collect(_process(*a))
            except Exception as e:  # noqa: BLE001
                errors[a[0]] = str(e)
                log.error("%s 失败: %s", a[0], e)

    if not covs:
        raise RuntimeError(f"所有标的都失败了: {errors}")
    pd.DataFrame(covs).to_csv(out / "coverage.csv", index=False)
    pd.concat(ics, ignore_index=True).to_csv(out / "ic.csv", index=False)
    pd.concat(seass, ignore_index=True).to_csv(out / "seasonality.csv", index=False)
    if oos:
        pd.concat(oos, ignore_index=True).to_csv(out / "oos_summary.csv", index=False)
        pd.concat(grids, ignore_index=True).to_csv(out / "full_grid.csv", index=False)
        pd.concat(folds, ignore_index=True).to_csv(out / "folds.csv", index=False)
        cv = pd.concat(curves, ignore_index=True)
        cv.to_csv(out / "oos_curves.csv.gz", index=False, compression="gzip")
        (out / "best_params.json").write_text(json.dumps(best, ensure_ascii=False, indent=1, default=_json_default))
    meta = {"interval": interval, "symbols": symbols, "start": start, "end": end, "errors": errors,
            "fee": cfg.fee, "slippage": cfg.slippage, "folds": cfg.folds,
            "initial_train_frac": cfg.initial_train_frac, "min_trades": cfg.min_trades,
            "exit_profiles": cfg.exit_profiles, "data_dir": str(data_dir),
            "elapsed_s": round(time.time() - t0, 1)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return out


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(type(o))
