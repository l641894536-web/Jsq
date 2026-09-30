"""命令行入口。

  python -m ashare_lab fetch [--stocks]            下载数据（需要能访问申万/东方财富）
  python -m ashare_lab check                       检查数据质量
  python -m ashare_lab run all                     在真实数据上跑全部研究，报告写到 reports/
  python -m ashare_lab run A C --synthetic         在合成数据上检查流程
  python -m ashare_lab run B --set common.entry_lag=0   稳健性：临时覆盖预注册参数
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .data.market import MarketData, load_csv_dir

STUDIES = {
    "A": ("a_lifecycle", "主线生命周期"),
    "B": ("b_crowding", "拥挤度"),
    "C": ("c_crash", "主线大跌"),
    "D": ("d_style", "风格切换"),
    "E": ("e_diffusion", "补涨扩散"),
    "F": ("f_regime", "市场环境与策略"),
    "G": ("g_exit", "退出规则"),
    "H": ("h_decompose", "拆解研究"),
}


def _parse_set(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try:
            out[k] = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            out[k] = v
    return out


def load_data(args, cfg) -> MarketData:
    if args.synthetic:
        from .data.synthetic import make_synthetic
        data, _ = make_synthetic(seed=args.seed, with_stocks=not args.no_stocks)
        return data
    return load_csv_dir(args.data_dir or cfg["data"]["dir"], cfg)


def cmd_run(args) -> int:
    import importlib

    from .studies.common import Panels

    cfg = load_config(args.config, _parse_set(args.set))
    ids = list(STUDIES) if (not args.studies or "all" in [s.lower() for s in args.studies]) else [s.upper() for s in args.studies]
    bad = [s for s in ids if s not in STUDIES]
    if bad:
        print(f"未知研究：{bad}；可选 {list(STUDIES)} 或 all")
        return 2
    data = load_data(args, cfg)
    print(data.summary())
    out = Path(args.out or ("reports/synthetic" if args.synthetic else "reports"))
    P = Panels(data, cfg)
    results = []
    for sid in ids:
        mod = importlib.import_module(f".studies.{STUDIES[sid][0]}", __package__)
        t0 = time.time()
        print(f"[{sid}] {STUDIES[sid][1]} ...", end=" ", flush=True)
        res = mod.run(P)
        path = res.save(out)
        print(f"{time.time() - t0:.1f}s → {path}")
        results.append(res)
    write_overview(results, out, data, cfg, args)
    print(f"总览：{out / '00_总览.md'}")
    return 0


def write_overview(results, out: Path, data: MarketData, cfg: dict, args) -> None:
    lines = ["# A股规律库｜验证总览", ""]
    if data.is_synthetic:
        lines += ["> ⚠️ **合成数据**：只用于检查代码流程，数字不代表任何A股结论。", ""]
    lines += [f"- {data.summary()}", f"- 参数：{args.config or 'config/default.toml'}"
              + (f"；临时覆盖：{args.set}" if args.set else ""), f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}", ""]
    lines += ["证据等级：A=样本≥20、FDR校正后q<0.05且前后两段同向；B=样本≥10、q<0.10且同向；C=不显著或前后不一致；D=样本<5。", ""]
    for r in results:
        lines += [f"## 研究{r.study_id}｜{r.title}", "", f"_{r.question}_", ""]
        lines += [f"- {f}" for f in r.findings] or ["- （无结论）"]
        lines += ["", f"详见 [{r.study_id}_{r.title}.md]({r.study_id}_{r.title}.md)", ""]
    (out / "00_总览.md").write_text("\n".join(lines), encoding="utf-8")


def cmd_fetch(args) -> int:
    from .data.fetch_akshare import fetch_all
    cfg = load_config(args.config)
    fetch_all(args.data_dir or cfg["data"]["dir"], start=args.start, stocks=args.stocks)
    return 0


def cmd_import_qlib(args) -> int:
    from .data.from_qlib import build_standard_dir
    from .data.industry_static import build_static_industry
    cfg = load_config(args.config)
    out = Path(args.data_dir or cfg["data"]["dir"])
    ind = Path(args.industry) if args.industry else out / "stock_industry_static.csv"
    if not ind.exists():
        build_static_industry(ind, out / "_src")
    build_standard_dir(args.qlib_dir, ind, out, start=args.start, weighting=args.weighting,
                       scheme=args.scheme, groups_sw1=cfg.get("groups", {}))
    print(f"完成：{out}。下一步：python -m ashare_lab --config {args.config or 'config/qlib.toml'} check")
    return 0


def cmd_check(args) -> int:
    cfg = load_config(args.config)
    data = load_data(args, cfg)
    print(data.summary())
    for n in data.notes:
        print("注意：", n)
    sc = data.sector_close
    print("\n行业数据覆盖：")
    cov = pd.DataFrame({
        "名称": [data.name(c) for c in sc.columns],
        "起始": [sc[c].first_valid_index() for c in sc.columns],
        "结束": [sc[c].last_valid_index() for c in sc.columns],
        "缺失收盘": sc.isna().sum().to_numpy(),
        "缺失成交额": data.sector_amount.isna().sum().to_numpy(),
    }, index=sc.columns)
    print(cov.to_string())
    ta = data.total_amount
    print(f"\n成交额分母缺失天数：{int(ta.isna().sum())} / {len(ta)}")
    share = data.turnover_share()
    print("\n各主题组合成交占比（研究区间）：")
    study = (share.index >= pd.Timestamp(cfg["data"]["study_start"]))
    for g, m in data.valid_groups().items():
        s = share.loc[study, m].sum(axis=1, min_count=len(m))
        if s.notna().any():
            print(f"  {g:<6} 中位 {s.median():.1%}  最高 {s.max():.1%}（{s.idxmax().date()}）  "
                  + "  ".join(f"≥{th:.0%}:{int((s >= th).sum())}天" for th in cfg["crowding"]["abs_thresholds"]))
    rets = sc.pct_change(fill_method=None)
    extreme = (rets.abs() > 0.15).sum()
    if extreme.any():
        print("\n单日涨跌超过15%的行业日（可能是数据错误）：")
        print(extreme[extreme > 0].to_string())
    print("\n指数缺失率（首个有效日之后）：")
    for code in data.index_close.columns:
        s = data.index_close[code]
        f0 = s.first_valid_index()
        if f0 is not None:
            print(f"  {code:<7}{data.name(code):<8} 起始 {f0.date()}  缺失 {s.loc[f0:].isna().mean():.1%}")
    miss_idx = [c for c in (cfg["data"]["market_index"], cfg["style"]["growth"], cfg["style"]["value"],
                            cfg["diffusion"]["small_index"], cfg["regime"]["dividend_index"]) if c not in data.index_close]
    if miss_idx:
        print(f"\n缺少指数：{miss_idx}（相关研究会降级或跳过）")
    print(f"\n宏观数据：{'有' if data.macro is not None else '无'}；个股：{'有' if data.stocks is not None else '无'}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ashare_lab", description="A股规律库：可证伪的规律验证")
    p.add_argument("--config", default=None, help="参数文件（默认 config/default.toml）")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="运行研究")
    r.add_argument("studies", nargs="*", help="A B C D E F 或 all")
    r.add_argument("--data-dir", default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--synthetic", action="store_true", help="使用合成数据（只检查流程）")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--no-stocks", action="store_true", help="合成数据不生成个股")
    r.add_argument("--set", action="append", help="临时覆盖参数，如 common.entry_lag=0（报告里会注明）")
    r.set_defaults(func=cmd_run)

    f = sub.add_parser("fetch", help="用 akshare 下载数据")
    f.add_argument("--data-dir", default=None)
    f.add_argument("--start", default="2010-01-01")
    f.add_argument("--stocks", action="store_true", help="同时下载个股（研究E、成交集中度需要；耗时较长）")
    f.set_defaults(func=cmd_fetch)

    q = sub.add_parser("import-qlib", help="把 qlib 格式A股日线（如 chenditc/investment_data）转换为标准数据目录")
    q.add_argument("qlib_dir")
    q.add_argument("--data-dir", default=None)
    q.add_argument("--industry", default=None, help="个股→申万一级映射 CSV；缺省时从 PyPI 包数据自动生成")
    q.add_argument("--start", default="2010-01-01")
    q.add_argument("--weighting", default="liquidity", choices=["liquidity", "equal"], help="行业指数加权方式")
    q.add_argument("--scheme", default="sw1", choices=["sw1", "em"], help="行业口径：申万一级 / 东财86细分行业")
    q.set_defaults(func=cmd_import_qlib)

    c = sub.add_parser("check", help="检查数据质量")
    c.add_argument("--data-dir", default=None)
    c.add_argument("--synthetic", action="store_true")
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--no-stocks", action="store_true")
    c.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    np.seterr(all="ignore")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
