"""Entry point: python -m market_data.run --mode full|smoke --data-dir data"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from . import a_share, binance, us
from .common import Stage, utcnow, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "smoke"], default="full")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--budget-min", type=float, default=290)
    ap.add_argument("--continue-flag", default="continue.flag")
    ap.add_argument("--only", default="", help="comma list of stages to run (binance,us,a_share)")
    args = ap.parse_args()

    t0 = time.time()
    deadline = t0 + args.budget_min * 60
    data = Path(args.data_dir)
    root = data / "_smoke" if args.mode == "smoke" else data
    if args.mode == "full" and (data / "_smoke").exists():
        shutil.rmtree(data / "_smoke")
    root.mkdir(parents=True, exist_ok=True)
    only = {s for s in args.only.split(",") if s}

    status_path = root / "status.json"
    prev = json.loads(status_path.read_text()) if status_path.exists() else {}
    status = {"mode": args.mode, "started_utc": utcnow().isoformat(timespec="seconds"),
              "stages": dict(prev.get("stages", {}))}

    uni_stage = Stage("us_universe")
    universe = us.load_universe(root, uni_stage)
    uni_stage.info["ok"] = True
    status["stages"]["us_universe"] = uni_stage.result()
    tickers = set(universe["ticker"])

    stock_perps: list[str] = []
    if not only or "binance" in only:
        # leave the bulk of the budget for A-shares
        status["stages"]["binance"], stock_perps = binance.run(root, args.mode,
                                                              min(deadline, time.time() + 60 * 60),
                                                              tickers)
        write_json(status, status_path)
    else:
        stock_perps = prev.get("stages", {}).get("binance", {}).get("stock_perps", [])

    if not only or "us" in only:
        status["stages"]["us"] = us.run(root, args.mode, min(deadline, time.time() + 60 * 60),
                                        universe, stock_perps)
        write_json(status, status_path)

    complete = True
    if not only or "a_share" in only:
        status["stages"]["a_share"], complete = a_share.run(root, args.mode, deadline - 15 * 60)

    status["finished_utc"] = utcnow().isoformat(timespec="seconds")
    status["minutes"] = round((time.time() - t0) / 60, 1)
    status["backfill_complete"] = complete
    runs = int(prev.get("continuation_runs", 0))
    a = status["stages"].get("a_share", {})
    if args.mode == "full" and not complete and a.get("progress_made") and runs < 12:
        Path(args.continue_flag).write_text("1")
        status["continuation_runs"] = runs + 1
    else:
        status["continuation_runs"] = 0 if complete else runs
    write_json(status, status_path)
    print(json.dumps({k: (v.get("ok"), v.get("n_errors")) for k, v in status["stages"].items()}))


if __name__ == "__main__":
    main()
