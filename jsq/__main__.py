"""命令行入口：python -m jsq <命令> -h 查看帮助。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from .config import (DATA_DIR, DEFAULT_INTERVAL, DEFAULT_START, RESULTS_DIR, SYMBOLS_FILE, BacktestConfig,
                     load_symbols)

log = logging.getLogger("jsq")


def _client(a):
    from .binance import BinanceClient
    return BinanceClient(proxy=a.proxy)


def _source(a) -> str:
    """auto：能连上币安 API 就用 API，否则用历史数据站。"""
    src = getattr(a, "source", "auto")
    if src != "auto":
        return src
    import requests
    proxies = {"http": a.proxy, "https": a.proxy} if a.proxy else None
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/time", timeout=8, proxies=proxies)
        r.raise_for_status()
        return "api"
    except Exception as e:  # noqa: BLE001
        log.info("币安 API 不可用（%s），改用历史数据站 data.binance.vision（数据截至上个完整月）", str(e)[:80])
        return "vision"


def cmd_discover(a):
    if _source(a) == "vision":
        from .vision import make_session, probe_symbols
        df = probe_symbols(make_session(a.proxy))
        ok = df[df["available"]]
        print(f"历史数据站 {df['month'].iloc[0]} 有数据的合约（共探测 {len(df)} 个候选）：\n")
        print(ok[["symbol", "category"]].to_string(index=False))
        keep = ok["symbol"].tolist()
    else:
        from .binance import classify_symbol
        df = _client(a).perpetual_symbols()
        df["category"] = [classify_symbol(b, u) for b, u in zip(df["base"], df["underlying_type"])]
        df = df[(df["status"] == "TRADING")]
        tradfi = df[df["category"] != ""].sort_values(["category", "symbol"])
        pd.set_option("display.width", 200)
        print(f"共 {len(df)} 个 USDT 永续在交易，其中非加密/TradFi 相关 {len(tradfi)} 个：\n")
        print(tradfi[["symbol", "category", "underlying_type", "underlying_sub_type", "onboard"]].to_string(index=False))
        keep = [s for s in dict.fromkeys(["BTCUSDT", "ETHUSDT"] + tradfi["symbol"].tolist()) if s in set(df["symbol"])]
    if a.save:
        SYMBOLS_FILE.write_text("\n".join(keep) + "\n")
        print(f"\n已写入 {SYMBOLS_FILE}（{len(keep)} 个），可手动编辑。之后命令默认使用该列表。")


def cmd_fetch(a):
    symbols = load_symbols(a.symbols)
    if _source(a) == "vision":
        from .vision import make_session, update_symbol_vision
        sess = make_session(a.proxy)
        for s in symbols:
            try:
                n = update_symbol_vision(sess, s, a.interval, a.start, Path(a.data_dir))
                if not n["klines"]:
                    log.warning("%s: 历史数据站没有该合约（代码不对或上线不足一个月）", s)
                else:
                    log.info("%s: K线 %d 根, 溢价 %d 根, 资金费 %d 条", s, n["klines"], n["premium"], n["funding"])
            except Exception as e:  # noqa: BLE001
                log.error("%s 下载失败: %s", s, e)
        return
    from .data import update_symbol
    client = _client(a)
    try:
        listed = set(client.perpetual_symbols()["symbol"])
        missing = [s for s in symbols if s not in listed]
        if missing:
            log.warning("交易所没有这些永续合约，已跳过: %s（运行 discover 查看可用代码）", ",".join(missing))
        symbols = [s for s in symbols if s in listed]
    except Exception as e:  # noqa: BLE001
        log.warning("获取交易所信息失败，跳过代码校验: %s", e)
    for s in symbols:
        try:
            n = update_symbol(client, s, a.interval, a.start, Path(a.data_dir))
            log.info("%s: K线 %d 根, 溢价 %d 根, 资金费 %d 条", s, n["klines"], n["premium"], n["funding"])
        except Exception as e:  # noqa: BLE001
            log.error("%s 下载失败: %s", s, e)


def cmd_fetch_extra(a):
    """持仓量/多空比/主动买卖比 + 订单簿深度（历史数据站日度文件，聚合成 1 小时）。"""
    from . import extra
    from .data import paths
    from .vision import make_session
    sess = make_session(a.proxy)
    kinds = ["metrics", "bookDepth"] if a.kind == "all" else [a.kind]
    for s in load_symbols(a.symbols):
        kp = paths(Path(a.data_dir), s, "1h")["klines"]
        listed = None
        if kp.exists():
            t0 = pd.read_csv(kp, usecols=["open_time"])["open_time"].min()
            listed = pd.Timestamp(int(t0), unit="ms").strftime("%Y-%m-%d")
        for k in kinds:
            try:
                n = extra.update(sess, s, k, a.start, Path(a.data_dir), listed_from=listed)
                log.info("%s %s: %d 小时", s, k, n)
            except Exception as e:  # noqa: BLE001
                log.error("%s %s 失败: %s", s, k, e)


def _cfg(a) -> BacktestConfig:
    return BacktestConfig(fee=a.fee, slippage=a.slippage, folds=a.folds, min_trades=a.min_trades,
                          initial_train_frac=a.train_frac)


def _available(symbols, a):
    from .data import paths
    ok = [s for s in symbols if paths(Path(a.data_dir), s, a.interval)["klines"].exists()]
    miss = sorted(set(symbols) - set(ok))
    if miss:
        log.warning("本地没有数据，跳过: %s（先运行 fetch）", ",".join(miss))
    if not ok:
        sys.exit("没有可用数据。先运行: python -m jsq fetch   （离线体验: python -m jsq demo）")
    return ok


def cmd_backtest(a, backtest=True):
    from .pipeline import run_pipeline
    from .report import build_report
    symbols = _available(load_symbols(a.symbols), a)
    out = run_pipeline(symbols, a.interval, Path(a.data_dir), _cfg(a), a.start_eval, a.end_eval,
                       a.strategies, a.jobs, backtest=backtest)
    rep = build_report(out)
    print(f"\n结果目录: {out}\n报告: {rep}")
    if backtest:
        _print_top(out)


def _print_top(out: Path, n=15):
    s = pd.read_csv(out / "oos_summary.csv")
    s = s[(s["strategy"] != "buy_hold") & (s["trades"] >= 15)].sort_values("sharpe", ascending=False).head(n)
    if not len(s):
        return
    view = pd.DataFrame({
        "标的": s["symbol"], "策略": s["label"], "笔数": s["trades"].astype(int),
        "胜率": (s["win_rate"] * 100).round(1), "总收益%": (s["total_return"] * 100).round(1),
        "回撤%": (s["max_drawdown"] * 100).round(1), "夏普": s["sharpe"].round(2),
        "持仓h": s["avg_hold_h"].round(1), "盈利段": s["folds_positive"].astype("Int64").astype(str) + "/" + s["folds"].astype(str),
    })
    print("\n样本外夏普 Top：")
    print(view.to_string(index=False))


def cmd_report(a):
    from .pipeline import latest_results_dir
    from .report import build_report
    d = Path(a.results) if a.results else latest_results_dir(Path(a.results_dir))
    print(build_report(d))


def cmd_signal(a):
    from .live import current_signals
    from .pipeline import latest_results_dir
    d = Path(a.results) if a.results else latest_results_dir(Path(a.results_dir))
    symbols = load_symbols(a.symbols) if a.symbols else None
    if not a.no_update:
        from .data import update_symbol
        import json
        client = _client(a)
        for s in symbols or list(json.loads((d / "best_params.json").read_text())):
            try:
                update_symbol(client, s, a.interval, a.start, Path(a.data_dir))
            except Exception as e:  # noqa: BLE001
                log.error("%s 更新失败，使用本地旧数据: %s", s, e)
    sig = current_signals(d, Path(a.data_dir), a.interval, symbols, a.top, a.min_sharpe)
    if not len(sig):
        print("没有满足条件（样本外夏普>%.2f）的策略。" % a.min_sharpe)
        return
    pd.set_option("display.width", 220)
    for sym, g in sig.groupby("symbol", sort=False):
        score = sum({"做多": 1, "做空": -1}.get(x, 0) for x in g["signal"])
        verdict = "偏多" if score > 0 else "偏空" if score < 0 else "中性"
        fa = g["funding_ann"].iloc[0]
        print(f"\n== {sym}  收盘 {g['close'].iloc[0]:.6g}  (K线 {g['bar_time'].iloc[0]} UTC)  "
              f"年化资金费率 {fa * 100:.1f}%  综合: {verdict} ({score:+d}/{len(g)})")
        v = g[["label", "signal", "since", "stop_ref", "tp_ref", "max_hold_h", "oos_sharpe", "oos_win_rate", "params", "exit"]]
        print(v.round({"stop_ref": 6, "tp_ref": 6, "oos_sharpe": 2, "oos_win_rate": 3}).to_string(index=False))
    out = d / "signals_latest.csv"
    sig.to_csv(out, index=False)
    print(f"\n已保存 {out}")


def cmd_demo(a):
    from .pipeline import run_pipeline
    from .report import build_report
    from .synthetic import make_dataset
    data_dir = Path(a.data_dir) / "_synthetic"
    syms = make_dataset(data_dir, a.interval)
    print(f"已生成合成数据 {syms} -> {data_dir}（仅用于演示流程，结果没有交易意义）")
    out = run_pipeline(syms, a.interval, data_dir, _cfg(a), strategy_names=a.strategies, jobs=a.jobs)
    print(f"报告: {build_report(out)}")
    _print_top(out)


def cmd_list(a):
    from .strategies import STRATEGIES
    for s in STRATEGIES.values():
        print(f"{s.name:18s} [{s.group}] {(s.fn.__doc__ or s.label).strip()}  ({len(s.param_sets())} 组参数)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m jsq", description="币安合约 资金费率/K线 多空策略研究工具")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, net=False, bt=False):
        sp.add_argument("--symbols", help="逗号分隔，如 BTCUSDT,XAUUSDT（默认读 symbols.txt）")
        sp.add_argument("--interval", default=DEFAULT_INTERVAL, help="K线周期，默认 1h")
        sp.add_argument("--data-dir", default=str(DATA_DIR))
        if net:
            sp.add_argument("--proxy", help="HTTP 代理，如 http://127.0.0.1:7890（也可设 HTTPS_PROXY 环境变量）")
            sp.add_argument("--start", default=DEFAULT_START, help="下载起始日期")
            sp.add_argument("--source", choices=["auto", "api", "vision"], default="auto",
                            help="数据源：api=币安实时接口，vision=币安历史数据站(按月,不受地区限制)，auto=自动")
        if bt:
            sp.add_argument("--strategies", help="只测这些策略，逗号分隔（list 查看）")
            sp.add_argument("--fee", type=float, default=0.0005, help="单边手续费，默认 0.0005")
            sp.add_argument("--slippage", type=float, default=0.0002, help="单边滑点，默认 0.0002")
            sp.add_argument("--folds", type=int, default=4, help="样本外段数")
            sp.add_argument("--train-frac", type=float, default=0.4, help="首个训练段占比")
            sp.add_argument("--min-trades", type=int, default=8, help="训练段最少交易数")
            sp.add_argument("--jobs", type=int, help="并行进程数")
            sp.add_argument("--start-eval", help="只用该日期之后的数据评估")
            sp.add_argument("--end-eval", help="只用该日期之前的数据评估")

    sp = sub.add_parser("discover", help="列出币安上黄金/白银/原油/美股等合约代码")
    sp.add_argument("--proxy")
    sp.add_argument("--source", choices=["auto", "api", "vision"], default="auto")
    sp.add_argument("--save", action="store_true", help="写入 symbols.txt")
    sp.set_defaults(func=cmd_discover)

    sp = sub.add_parser("fetch", help="下载/增量更新 K线、溢价指数、资金费率")
    common(sp, net=True)
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("fetch-extra", help="下载持仓量/多空比/订单簿深度（历史数据站）")
    common(sp, net=True)
    sp.add_argument("--kind", choices=["all", "metrics", "bookDepth"], default="all")
    sp.set_defaults(func=cmd_fetch_extra)

    sp = sub.add_parser("analyze", help="只做因子预测力分析（IC），不回测")
    common(sp, bt=True)
    sp.set_defaults(func=lambda a: cmd_backtest(a, backtest=False))

    sp = sub.add_parser("backtest", help="全部策略 × 标的 滚动样本外回测 + 报告")
    common(sp, bt=True)
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("run", help="fetch + backtest 一条龙")
    common(sp, net=True, bt=True)
    sp.set_defaults(func=lambda a: (cmd_fetch(a), cmd_backtest(a)))

    sp = sub.add_parser("report", help="重新生成 HTML 报告")
    sp.add_argument("--results", help="结果目录，默认最近一次")
    sp.add_argument("--results-dir", default=str(RESULTS_DIR))
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("signal", help="用回测选出的参数给出当前多空信号")
    common(sp, net=True)
    sp.add_argument("--results", help="结果目录，默认最近一次")
    sp.add_argument("--results-dir", default=str(RESULTS_DIR))
    sp.add_argument("--top", type=int, default=3, help="每个标的取样本外最好的前 N 个策略")
    sp.add_argument("--min-sharpe", type=float, default=0.3, help="样本外夏普门槛")
    sp.add_argument("--no-update", action="store_true", help="不联网更新数据")
    sp.set_defaults(func=cmd_signal)

    sp = sub.add_parser("demo", help="用合成数据离线跑通全流程")
    common(sp, bt=True)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("list", help="列出所有策略")
    sp.set_defaults(func=cmd_list)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    a.func(a)


if __name__ == "__main__":
    main()
