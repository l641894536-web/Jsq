"""命令行：

    python -m indicator_lab calibrate                 # 第0步：模拟数据上的误报率与检验力
    python -m indicator_lab run --stage dv            # 第1~5步：发现集 + 验证集（测试集数据不进入内存）
    python -m indicator_lab run --stage test          # 第6步：最终测试集（只在测试前判定提交后运行一次）
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import report as RP
from . import runner as R

DEFAULT_OUT = "results/indicators_2026-09-29"


def _log(path: Path | None):
    def f(msg: str):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    return f


def _calib_one(args) -> dict:
    cfg_path, seed, plant, n_stocks = args
    from .synthetic import synthetic_panel
    cfg = R.load_cfg(cfg_path)
    P = synthetic_panel(n_stocks=n_stocks, seed=seed, plant=plant)
    daily, ctx = R.run_signals(P, cfg, "dv", log=lambda m: None)
    summ = R.summarize(daily, ctx, cfg)
    out = R.verdict_dv(P, daily, ctx, summ, cfg, log=lambda m: None)
    v = out["verdict"]
    val = summ[summ.split == "validation"]
    return {"seed": seed, "plant": plant, "verdict": v, "placebo_t": val["placebo_t"].to_numpy()}


def cmd_calibrate(a) -> None:
    out = Path(a.out) / "calibration"
    (out / "csv").mkdir(parents=True, exist_ok=True)
    jobs = [(a.config, s, 0.0, a.n_stocks) for s in a.seeds] + [(a.config, 100, a.plant, a.n_stocks)]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(_calib_one, jobs))
    rows = []
    planted = None
    for r in res:
        v = r["verdict"]
        v.to_csv(out / "csv" / f"verdict_seed{r['seed']}_plant{r['plant']}.csv", index=False, encoding="utf-8-sig")
        if r["plant"] > 0:
            planted = r
            continue
        t = v["stat_t"].abs()
        rows.append({"随机种子": r["seed"], "检验数": int(np.isfinite(v["stat_t"]).sum()),
                     "|t|>2 个数": int((t > 2).sum()), "|t|>3 个数": int((t > 3).sum()),
                     "q<0.05 个数": int((v["q"] < 0.05).sum()), "判为显著 个数": int(v["sig"].sum()),
                     "A候选 个数": int((v["pre_grade"] == "A候选").sum()),
                     "最小 RC p值": float(v["rc_p"].min()),
                     "安慰剂|t|>3 个数": int((np.abs(r["placebo_t"]) > 3).sum()),
                     "净超额CI>0 个数(不看显著性)": int(v["bt_ok"].sum())})
    pl = None
    if planted:
        v = planted["verdict"]
        top = v[v.h == 5].reindex(v[v.h == 5]["stat_t"].abs().sort_values(ascending=False).index).head(15)
        tbl = pd.DataFrame({"信号": top["signal"], "验证集 IC": top["ic_mean"], "验证集 t值": top["stat_t"],
                            "显著": top["sig"], "FM t值": top["fm_t"], "年化超额(净0.3%)": top["ann_net"],
                            "90%CI下限": top["ci_lo"], "测试前等级": top["pre_grade"]})
        n_sig = int(v["sig"].sum())
        note = (f"埋入强度 {a.plant}：次日对数收益期望 = −{a.plant}×个股波动×过去5日收益的横截面标准分（真实短期反转量级）。"
                f"表中为 5 日持有期 |t| 最大的 15 个信号；全部 222 项中判为显著 {n_sig} 项。")
        pl = {"table": tbl, "note": note, "pct": ["年化超额(净0.3%)", "90%CI下限"]}
    meta = [f"- 运行：{len(jobs)} 套模拟数据，用时 {time.time() - t0:.0f} 秒；判定门槛与真实数据完全相同（config/indicators.toml）。"]
    RP.save(out / "第0步_误报率与检验力.md", RP.calibration_doc(rows, pl, meta))
    print(pd.DataFrame(rows).to_string())
    if pl:
        print(pl["table"].to_string())


def _stage_meta(P, ctx) -> dict:
    E = ctx["E"]
    meta = {"数据": f"{P.dates[0]:%Y-%m-%d} ~ {P.dates[-1]:%Y-%m-%d}，{P.m} 只股票（含已退市）"}
    for sp in ("discovery", "validation", "test"):
        m = ctx["split"] == sp
        if m.any():
            d = ctx["dates"][m]
            meta[R.SPLIT_CN[sp]] = f"{d[0]:%Y-%m-%d} ~ {d[-1]:%Y-%m-%d}，{m.sum()} 个交易日，日均可入选 {E[m].sum(1).mean():.0f} 只"
    return meta


def cmd_run(a) -> None:
    from .panel import load_panel
    cfg = R.load_cfg(a.config)
    cfg["_real"] = True
    out = Path(a.out)
    (out / "csv").mkdir(parents=True, exist_ok=True)
    log = _log(out / f"run_{a.stage}.log")
    d = cfg["data"]
    if a.stage == "dv":
        end = cfg["split"]["validation"][1]
        log(f"载入面板（截断到验证集最后一天 {end}，测试集数据不进入内存）")
        P = load_panel(d["qlib_dir"], d["start"], d["industry_csv"], max_stocks=a.max_stocks, end=end, log=log)
        daily, ctx = R.run_signals(P, cfg, "dv", log=log)
        summ = R.summarize(daily, ctx, cfg)
        summ.to_csv(out / "csv" / "summary_dv.csv", index=False, encoding="utf-8-sig")
        res = R.verdict_dv(P, daily, ctx, summ, cfg, log=log)
        res["verdict"].to_csv(out / "csv" / "verdict_dv.csv", index=False, encoding="utf-8-sig")
        res["regime"].to_csv(out / "csv" / "regime_ic_validation.csv", index=False, encoding="utf-8-sig")
        for sp in ("discovery", "validation"):
            X, keys = R.primary_matrix(daily, ctx, cfg, sp)
            X.columns = [f"{s}|{h}" for s, h in keys]
            X.to_csv(out / "csv" / f"daily_primary_{sp}.csv.gz", float_format="%.5f")
        meta = _stage_meta(P, ctx)
        RP.write_dv(out, summ, res, cfg, meta)
        if a.cache:
            Path(a.cache).parent.mkdir(parents=True, exist_ok=True)
            pd.to_pickle({"daily": daily, "dates": ctx["dates"], "split": ctx["split"], "valid": ctx["valid"]}, a.cache)
        log("完成：发现集 + 验证集")
    else:
        vpath = out / "csv" / "verdict_dv.csv"
        if not vpath.exists():
            sys.exit("缺少测试前判定（先运行 --stage dv 并提交判定）")
        v = pd.read_csv(vpath)
        directions = {(r.signal, int(r.h)): float(r.direction) for r in v.itertuples()}
        log("载入完整面板（含测试集）")
        P = load_panel(d["qlib_dir"], d["start"], d["industry_csv"], max_stocks=a.max_stocks, log=log)
        daily, ctx = R.run_signals(P, cfg, "test", directions=directions, log=log)
        summ = R.summarize(daily, ctx, cfg)
        summ.to_csv(out / "csv" / "summary_test.csv", index=False, encoding="utf-8-sig")
        f = RP.final_grades(v, summ, cfg)
        f.to_csv(out / "csv" / "final_grades.csv", index=False, encoding="utf-8-sig")
        RP.write_test(out, f, _stage_meta(P, ctx))
        log("完成：最终测试集")


def cmd_timing(a) -> None:
    from .timing import run_timing
    cfg = R.load_cfg(a.config)
    out = Path(a.out) / ("timing_null" if a.synthetic is not None else "timing")
    (out / "csv").mkdir(parents=True, exist_ok=True)
    log = _log(None)
    if a.synthetic is not None:
        from .synthetic import synthetic_panel
        P = synthetic_panel(n_stocks=1500, seed=a.synthetic)
        res = run_timing(P, cfg, real=False, log=log)
    else:
        from .panel import load_panel
        d = cfg["data"]
        P = load_panel(d["qlib_dir"], d["start"], d["industry_csv"], log=log)
        res = run_timing(P, cfg, real=True, log=log)
    res["tests"].to_csv(out / "csv" / "timing_tests.csv", index=False, encoding="utf-8-sig")
    if len(res["timing"]):
        res["timing"].to_csv(out / "csv" / "timing_backtest.csv.gz", index=False, encoding="utf-8-sig", float_format="%.5f")
    RP.write_timing(out, res, cfg, synthetic=a.synthetic is not None)
    t = res["tests"]
    print(t.groupby(["group", "h"])["sig"].sum().to_string())


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="indicator_lab")
    p.add_argument("--config", default="config/indicators.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    c.add_argument("--plant", type=float, default=0.02)
    c.add_argument("--n-stocks", type=int, default=1000)
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--out", default=DEFAULT_OUT)
    r = sub.add_parser("run")
    r.add_argument("--stage", choices=["dv", "test"], required=True)
    r.add_argument("--max-stocks", type=int, default=None)
    r.add_argument("--out", default=DEFAULT_OUT)
    r.add_argument("--cache", default="data/indicator_cache/daily_dv.pkl")
    t = sub.add_parser("timing")
    t.add_argument("--synthetic", type=int, default=None, help="零假设模拟面板的随机种子（误报率自检）")
    t.add_argument("--out", default=DEFAULT_OUT)
    a = p.parse_args(argv)
    {"calibrate": cmd_calibrate, "run": cmd_run, "timing": cmd_timing}[a.cmd](a)


if __name__ == "__main__":
    main()
