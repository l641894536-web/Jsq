"""命令行入口：python -m jsq <命令> -h 查看帮助。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
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


def cmd_classlab(a):
    from .classlab import run_all
    from .class_report import build_class_report
    from .pipeline import new_results_dir
    symbols = _available(load_symbols(a.symbols), a)
    out = new_results_dir()
    cfg = _cfg(a)
    from .classlab import CLASS_EXITS
    exits = {k: CLASS_EXITS[k] for k in a.exits.split(",")} if a.exits else None
    strategies = [x.strip() for x in a.strategies.split(",")] if a.strategies else None
    run_all(symbols, a.interval, Path(a.data_dir), cfg.cost, out, folds=a.folds, strategies=strategies,
            jobs=a.jobs or 4, exits=exits)
    print(f"\n结果目录: {out}\n报告: {build_class_report(out, fee=cfg.fee, slippage=cfg.slippage)}")


def cmd_class_signal(a):
    from . import extra
    from .data import load_frame, update_symbol
    from .live_class import class_signals, latest_class_dir
    d = Path(a.results) if a.results else latest_class_dir(Path(a.results_dir))
    symbols = _available(load_symbols(a.symbols), a)
    if not a.no_update:
        client = _client(a)
        for s in symbols:
            try:
                update_symbol(client, s, a.interval, a.start, Path(a.data_dir))
                extra.update_live(client, s, Path(a.data_dir))
            except Exception as e:  # noqa: BLE001
                log.warning("%s 实时更新失败，使用本地数据: %s", s, str(e)[:120])
    frames = {}
    for s in symbols:
        try:
            frames[s] = load_frame(s, a.interval, Path(a.data_dir))
        except FileNotFoundError:
            pass
    only = [x.strip() for x in a.strategies.split(",")] if a.strategies else None
    sig = class_signals(d, frames, a.fee + a.slippage, only=only, min_exp_bps=a.min_exp)
    if not len(sig):
        print("没有样本外期望为正的配置。可以用 --strategies 指定策略。")
        return
    side = {1: "做多", -1: "做空", 0: "空仓"}
    pd.set_option("display.width", 220)
    for (g, name), x in sig.groupby(["group", "strategy"], sort=False):
        r0 = x.iloc[0]
        print(f"\n== {g} · {r0['label']} {r0['params']} · {r0['filter']} · {r0['exit']} · "
              f"样本外每笔 {r0['oos_exp_bps']:.1f} 基点 胜率 {r0['oos_win_rate']:.0%} 盈亏比 {r0['oos_payoff']:.2f}")
        for r in x.itertuples():
            line = f"  {r.symbol:10s} {r.bar_time} 收盘 {r.close:<10.6g} 行情 {r.regime or '-':6s} 持仓 {side[r.position]}"
            if r.position:
                line += (f"  开仓 {r.entry_time} @ {r.entry_px:.6g}  浮盈 {r.pnl_pct:+.2f}%  已持有 {r.held_h:.0f}h"
                         + (f"  止损 {r.stop:.6g}" if r.stop == r.stop else "")
                         + (f"  参考止损(4ATR) {r.ref_stop:.6g}" if getattr(r, "ref_stop", np.nan) == getattr(r, "ref_stop", np.nan) else "")
                         + (f"  止盈 {r.take_profit:.6g}" if r.take_profit == r.take_profit else "")
                         + (f"  最长 {r.max_hold_h:.0f}h" if r.max_hold_h == r.max_hold_h else ""))
            elif r.raw_signal:
                line += f"  （原始信号{side[r.raw_signal]}，但开仓时行情不符合过滤条件）"
            print(line)
    out = d / "class_signals_latest.csv"
    sig.to_csv(out, index=False)
    print(f"\n已保存 {out}")


def cmd_fetch_news(a):
    from . import news
    from .vision import make_session
    sess = make_session(a.proxy)
    for t in (a.topics.split(",") if a.topics else news.TOPICS):
        try:
            n = news.update(sess, t, Path(a.data_dir), days=a.days, pause=a.pause)
            log.info("新闻 %s: %d 条（15 分钟）", t, n)
        except Exception as e:  # noqa: BLE001
            log.error("新闻 %s 下载失败: %s", t, e)


def cmd_newslab(a):
    from . import newslab
    from .class_report import build_class_report
    from .classlab import run_all
    from .cross import group_of
    from .data import load_frame
    from .pipeline import new_results_dir
    syms = [s for s in _available(load_symbols(a.symbols), a) if group_of(s) in ("能源", "贵金属")]
    frames = [load_frame(s, a.interval, Path(a.data_dir)) for s in syms]
    if not any(c.startswith("news_") for f in frames for c in f.columns):
        sys.exit("没有新闻数据。先运行: python -m jsq fetch-news")
    out = new_results_dir()
    cfg = _cfg(a)
    ev, summ = newslab.run(frames, cfg.cost)
    ev.to_csv(out / "news_events.csv", index=False)
    summ.to_csv(out / "news_summary.csv", index=False)
    run_all(syms, a.interval, Path(a.data_dir), cfg.cost, out, folds=a.folds, jobs=a.jobs or 2)
    print(f"\n新闻事件 {len(ev)} 个；结果目录: {out}\n报告: {build_class_report(out, fee=cfg.fee, slippage=cfg.slippage)}")


def cmd_hk_study(a):
    import json
    from . import hk, hk_micro, hk_report
    from .pipeline import new_results_dir
    from .vision import make_session
    d = Path(a.data_dir) / "hk1m"
    d.mkdir(parents=True, exist_ok=True)
    syms = [x.strip() for x in a.symbols.split(",")] if a.symbols else hk.HK_SYMBOLS
    if not a.no_update:
        sess = make_session(a.proxy)
        log.info("BABAUSDT（夜盘参照）1 分钟数据: %s", hk.update(sess, "BABAUSDT", d))
        for s in syms:
            log.info("%s 1 分钟数据: %s", s, hk.update(sess, s, d))
            if not a.skip_ticks:
                n = len(hk_micro.collect(sess, s, Path(a.data_dir) / "hkmicro"))
                log.info("%s 逐笔成本统计: %d 行", s, n)
    data = hk_report.build_data(Path(a.data_dir), syms, slippage=a.slippage)
    out = new_results_dir()
    (out / "hk_report_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    rep = hk_report.build_html(data, out / "hk_report.html", fragment=False)
    hk_report.build_html(data, out / "hk_report_artifact.html", fragment=True)
    pd.set_option("display.width", 220)
    print("\n跳空被合约提前反映的比例：")
    print(pd.DataFrame(data["prepricing"]).to_string(index=False))
    print("\n按竞价方向追单，按隔夜合约是否走过头分组（每笔基点）：")
    print(pd.DataFrame(data["cats"]).drop(columns="key").to_string(index=False))
    t = data["tiles"]
    print(f"\n开盘后价差收敛（09:31 偏离 >0.3% 反向，持有到 11:59）：每笔 {t['exp_real']} 基点（实测成本），"
          f"t={t['t']}，胜率 {t['win']}%，{t['trades']} 笔")
    print(pd.DataFrame(data["by_symbol"]).drop(columns=["symbol", "weak"]).to_string(index=False))
    print(pd.DataFrame(data["stops"]).to_string(index=False))
    o = data["overnight"]
    print("\n收盘后合约走势（按当天正股涨跌，每格 = 平均基点 / 上涨占比%）：")
    print(pd.DataFrame(o["after"]).to_string(index=False))
    print("\n白天涨跌 × 夜里涨跌（open/am：顺夜里方向为正，回落为负）：")
    print(pd.DataFrame(o["cases"]).to_string(index=False))
    print("\n开盘前规则（扣成本后）：")
    print(pd.DataFrame(o["rules"]).to_string(index=False))
    print(f"\n结果目录: {out}\n报告: {rep}")


def cmd_hk_now(a):
    """实时：开盘前输入竞价涨跌幅，看合约还剩多少没反映；开盘后看合约与正股的价差。需要能访问币安接口。"""
    import time
    if not a.watch:
        return _hk_now_once(a)
    try:
        while True:
            print("\033[2J\033[H", end="")   # 清屏
            _hk_now_once(a)
            time.sleep(a.watch)
    except KeyboardInterrupt:
        pass


def _hk_now_once(a):
    import json
    from . import hk
    from . import hk_overnight as ho
    client = _client(a)
    auction = {}
    for kv in (a.auction or "").split(","):
        if "=" in kv:
            k, v = kv.split("=")
            auction[k.strip().upper()] = float(v) / 100
    syms = list(auction) or ([x.strip() for x in a.symbols.split(",")] if a.symbols else hk.HK_SYMBOLS)
    now = pd.Timestamp.now(tz="Asia/Hong_Kong")
    hm = now.hour * 60 + now.minute
    close_day = pd.Timestamp(a.prev_day, tz="Asia/Hong_Kong") if a.prev_day else ho.reference_close(now)
    before = close_day - pd.offsets.BDay(1)
    ms = lambda day: int((day.normalize() + pd.Timedelta(hours=16, minutes=10)).timestamp() * 1000)  # noqa: E731
    t_close, t_before = ms(close_day), ms(before)
    # 最近一次研究结果里的规则统计，用来给出历史胜率
    rules = None
    try:
        from .pipeline import RESULTS_DIR
        cands = sorted(Path(RESULTS_DIR).glob("*/hk_report_data.json"))
        if cands:
            rules = json.loads(cands[-1].read_text()).get("overnight", {}).get("rules")
    except Exception:  # noqa: BLE001
        rules = None

    def kline_close(sym, t, index=False):
        if index:
            k = client.get("/fapi/v1/indexPriceKlines", {"pair": sym, "interval": "1m", "startTime": t, "limit": 1})
        else:
            k = client.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": t, "limit": 1})
        return float(k[0][4]) if k else np.nan

    print(f"现在 {now:%Y-%m-%d %H:%M} 香港时间；参照收盘 {close_day:%Y-%m-%d} 16:10（遇港股假期请用 --prev-day 指定）")
    try:
        baba = float(client.get("/fapi/v1/ticker/price", {"symbol": "BABAUSDT"})["price"]) / kline_close("BABAUSDT", t_close) - 1
        print("  " + ho.advise_baba(baba))
    except Exception as e:  # noqa: BLE001
        print(f"  阿里美股合约获取失败：{str(e)[:80]}")
    for s in syms:
        try:
            pi = client.get("/fapi/v1/premiumIndex", {"symbol": s})
            last = float(client.get("/fapi/v1/ticker/price", {"symbol": s})["price"])
            perp_close, idx_close = kline_close(s, t_close), kline_close(s, t_close, index=True)
            idx_before = kline_close(s, t_before, index=True)
        except Exception as e:  # noqa: BLE001
            print(f"{s}: 获取失败 {str(e)[:100]}")
            continue
        move = last / perp_close - 1
        day_chg = idx_close / idx_before - 1
        print(f"\n{s}  合约 {last:.5g} | 收盘日正股 {day_chg:+.2%}，收盘时合约比正股 {perp_close / idx_close - 1:+.2%}"
              f" | 合约自收盘 {move:+.2%}")
        in_session = (9 * 60 + 30 <= hm < 12 * 60) or (13 * 60 <= hm < 16 * 60 + 10)
        if not in_session:
            print("  " + ho.advise_overnight(move, hm, rules))
        if s in auction:
            rem = hk.remaining_gap(auction[s], move)
            print(f"  竞价 {auction[s]:+.2%} → 合约还差 {rem:+.2%}：{hk.advise_preopen(rem, auction[s])}")
        if 9 * 60 + 31 <= hm < 12 * 60:
            basis = last / float(pi["indexPrice"]) - 1
            print(f"  合约/正股 {basis:+.2%}：{hk.advise_open(basis, symbol=s)}")


def cmd_excursion(a):
    from . import excursion as ex
    from .pipeline import RESULTS_DIR, new_results_dir
    pd.set_option("display.width", 220)
    out = new_results_dir()
    pct = lambda x: f"{x:.0%}"
    print("方向对 = +1R 比 -1R 先到；对照 = 同一时刻随机猜方向（波动一样）。比对照高才说明方向判断有用。")
    P, O, split = ex.hk_inputs(Path(a.data_dir))
    g = ex._hk_gather(P, O)
    hk_rows = pd.concat([ex.hk_study(P, O, split, r_pct=r / 100, gathered=g) for r in a.hk_r], ignore_index=True)
    if len(hk_rows):
        hk_rows.to_csv(out / "excursion_hk.csv", index=False)
        print("\n港股合约规则（每笔期望 = 扣成本后平均赚多少，% ；止损 = 1R）：")
        for r in hk_rows.to_dict("records"):
            grid = "  ".join(f"止盈{k:g}R:{r[f'E{k}'] * r['R_pct']:+.2f}%" for k in ex.FAV)
            print(f"  {r['rule']} → {r['exit']}平 | 止损 {r['R_pct']:g}% | {r['n']} 次 | 方向对 {pct(r['right'])}"
                  f"（对照 {pct(r['right_base'])}） 方向错 {pct(r['wrong'])}（对照 {pct(r['wrong_base'])}）"
                  f" 没走出来 {pct(r['none'])}\n      {grid}")
        sg = ex.hk_stop_grid(P, O, split, gathered=g)
        sg.to_csv(out / "excursion_hk_stops.csv", index=False)
        print(f"\n不设止盈、到点平仓，只改止损宽度（每笔 % / 胜率；括号为 {split} 前后两段）：")
        for (rule, ex_hm), gg in sg.groupby(["rule", "exit"], sort=False):
            cells = [f"{'不设' if pd.isna(r.stop) else f'{r.stop:.0%}'} {r.exp_bps / 100:+.2f}%/{r.win:.0%}"
                     f"({r.first_bps / 100:+.2f}/{r.second_bps / 100:+.2f})" for r in gg.itertuples()]
            print(f"  {rule} → {ex_hm}平 | " + " | ".join(cells))
    cands = sorted(Path(RESULTS_DIR).glob("*/class_folds.csv"))
    cdir = Path(a.class_results) if a.class_results else (cands[-1].parent if cands else None)
    if cdir is not None:
        cl = ex.class_study(cdir, Path(a.data_dir), r_atr=a.r_atr, horizon_h=a.horizon)
        if len(cl):
            cl.to_csv(out / "excursion_class.csv", index=False)
            cols = ["group", "strategy", "n", "right", "right_base", "right_t", "wrong", "wrong_base", "half",
                    "half_base", "best_k", "best_E", "B1.0"]
            print(f"\n分类研究的策略（样本外开仓，1R = {a.r_atr:g} 倍 1 小时 ATR，最长看 {a.horizon} 小时；"
                  f"best_E / B1.0 = 扣费后每笔 R）：")
            print(cl.sort_values("right_t", ascending=False)[cols].round(2).to_string(index=False))
    print(f"\n结果目录: {out}")


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

    sp = sub.add_parser("classlab", help="按资产类别研究：分类策略库 + 同类合并检验 + 行情状态 + 持仓时间曲线")
    common(sp, bt=True)
    sp.add_argument("--exits", help="只用这些出场方式，例如 h48,h96,h168（可选: sig,sl2tp6,trail4,h12,h24,h48,h96,h168）")
    sp.set_defaults(func=cmd_classlab, folds=3)

    sp = sub.add_parser("class-signal", help="用分类研究选出的配置给出各标的当前持仓状态")
    common(sp, net=True)
    sp.add_argument("--results", help="分类研究结果目录，默认最近一次")
    sp.add_argument("--results-dir", default=str(RESULTS_DIR))
    sp.add_argument("--strategies", help="只看这些策略，例如 smart_follow")
    sp.add_argument("--min-exp", type=float, default=0.0, help="样本外每笔期望门槛（基点）")
    sp.add_argument("--fee", type=float, default=0.0005)
    sp.add_argument("--slippage", type=float, default=0.0002)
    sp.add_argument("--no-update", action="store_true", help="不联网更新，只用本地数据")
    sp.set_defaults(func=cmd_class_signal)

    sp = sub.add_parser("fetch-news", help="下载 GDELT 新闻报道量/情绪（最近约 3 个月）")
    sp.add_argument("--data-dir", default=str(DATA_DIR))
    sp.add_argument("--proxy")
    sp.add_argument("--topics", help="逗号分隔：oil,trump_energy,opec,mideast,russia_oil")
    sp.add_argument("--days", type=int, default=90)
    sp.add_argument("--pause", type=float, default=5.0, help="每次请求间隔秒数（GDELT 要求限速）")
    sp.set_defaults(func=cmd_fetch_news)

    sp = sub.add_parser("newslab", help="新闻事件研究（能源/贵金属）+ 含新闻策略的分类回测")
    common(sp, bt=True)
    sp.set_defaults(func=cmd_newslab, folds=3)

    sp = sub.add_parser("hk-study", help="港股合约：开盘跳空被提前定价的研究（1 分钟数据）")
    sp.add_argument("--symbols")
    sp.add_argument("--data-dir", default=str(DATA_DIR))
    sp.add_argument("--proxy")
    sp.add_argument("--no-update", action="store_true")
    sp.add_argument("--skip-ticks", action="store_true", help="不更新逐笔成交/订单簿成本统计（较慢）")
    sp.add_argument("--slippage", type=float, default=0.0005, help="假设的单边滑点，默认 0.05%%（另有实测价差版本）")
    sp.set_defaults(func=cmd_hk_study)

    sp = sub.add_parser("hk-now", help="港股合约实时：竞价还剩多少没反映 / 开盘后合约与正股价差")
    sp.add_argument("--symbols")
    sp.add_argument("--auction", help="竞价相对昨收的涨跌幅(%%)，如 ZHIPUUSDT=-2.3,MINIMAXUSDT=1.5")
    sp.add_argument("--prev-day", help="上一交易日 YYYY-MM-DD（默认上一个工作日，遇港股假期请手动指定）")
    sp.add_argument("--proxy")
    sp.add_argument("--watch", type=int, default=0, help="每 N 秒刷新一次（Ctrl+C 退出），如 --watch 30")
    sp.set_defaults(func=cmd_hk_now)

    sp = sub.add_parser("excursion", help="方向对不对 vs 能走多远：开仓后最大浮盈/浮亏分析（港股规则 + 分类研究的策略）")
    sp.add_argument("--data-dir", default=str(DATA_DIR))
    sp.add_argument("--hk-r", type=float, nargs="+", default=[1.0, 2.0], help="港股：1R = 开仓价的百分之几，可给多个")
    sp.add_argument("--r-atr", type=float, default=4.0, help="分类策略：1R = 几倍 1 小时 ATR（默认 4，与止损一致）")
    sp.add_argument("--horizon", type=int, default=72, help="分类策略：开仓后最多看多少小时（默认 72）")
    sp.add_argument("--class-results", help="classlab 结果目录（默认最近一次）")
    sp.set_defaults(func=cmd_excursion)

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
