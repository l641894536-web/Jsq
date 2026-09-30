"""样本外跟踪：信号快照（monitor）与样本外计分板（scoreboard）。

规则定义冻结在 docs/rulebook.md；这里的实现必须与研究I、研究C保持一致。
- monitor：用最新数据生成当日信号快照；把信号日 ≥ oos.start 的 R1/R2 信号追加到日志（同一信号只记一次）。
- scoreboard：对日志中已到期的信号计算实际结果，按手册里的判定标准给出“进度/确认/失效”。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .core import returns as R
from .core import stats
from .core.events import crossing_events
from .report import StudyResult, pct
from .studies.common import Panels

LOG_COLS = ["signal_id", "rule", "unit", "code", "signal_date", "detail", "prediction", "logged_asof", "logged_at"]


def _units(P: Panels) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """R1 的跟踪对象：主题组合 + 各行业。返回 (收盘, 成交占比, 名称→代码)。"""
    from .studies.b_crowding import unit_panels
    closes, shares = unit_panels(P)
    codes = {g: g for g in closes.columns}
    for code in P.data.sector_close.columns:
        nm = P.data.name(code)
        if nm in closes.columns:
            continue
        closes[nm] = P.data.sector_close[code]
        shares[nm] = P.share[code]
        codes[nm] = code
    return closes, shares, codes


def r1_signals(P: Panels) -> pd.DataFrame:
    c = P.cfg["portfolio"]
    cc = P.cfg["common"]
    closes, shares, codes = _units(P)
    spct = R.rolling_percentile_frame(shares, cc["pct_window"], cc["pct_min_periods"])
    rows = []
    for u in spct.columns:
        for d in crossing_events(spct[u], c["crowd_pct"], rearm=c["crowd_pct"] - 0.10, min_gap=P.cfg["crowding"]["min_gap_days"]):
            rows.append({"unit": u, "code": codes[u], "signal_date": d, "share": shares.at[d, u], "share_pct": spct.at[d, u]})
    return pd.DataFrame(rows, columns=["unit", "code", "signal_date", "share", "share_pct"])


def snapshot(P: Panels) -> tuple[StudyResult, pd.DataFrame]:
    from .studies.a_lifecycle import detect_episodes
    from .studies.f_regime import regime_labels
    from .studies.i_portfolio import r2_events
    c = P.cfg["portfolio"]
    dates = P.data.dates
    asof = dates[-1]
    n = len(dates)
    res = StudyResult("M", f"信号快照_{asof.date()}", f"截至 {asof.date()} 的规则信号（规则定义见 docs/rulebook.md）", meta=P.meta())
    log_rows = []
    oos_start = pd.Timestamp(P.cfg["oos"]["start"])

    # R1
    r1 = r1_signals(P)
    avoid = int(c["avoid_days"])
    recent = r1[r1["signal_date"] >= dates[max(0, n - avoid)]].copy()
    if not recent.empty:
        recent["已过交易日"] = [n - 1 - dates.get_loc(d) for d in recent["signal_date"]]
        recent["还需回避(交易日)"] = avoid - recent["已过交易日"]
        _, shares, _ = _units(P)
        recent["当前成交占比"] = [shares[u].iloc[-1] for u in recent["unit"]]
    res.add("R1 拥挤回避名单（近 60 个交易日内触发）", recent.rename(columns={"unit": "对象", "signal_date": "触发日", "share": "触发日占比", "share_pct": "触发日分位"}).drop(columns=["code"]) if not recent.empty else recent,
            "预测：触发后 20/60 个交易日相对市场跑输（样本内 −1.3% / −2.0%）。", pct_cols=["触发日占比", "触发日分位", "当前成交占比"])
    for _, r in r1[r1["signal_date"] >= oos_start].iterrows():
        log_rows.append({"signal_id": f"R1|{r['unit']}|{r['signal_date'].date()}", "rule": "R1", "unit": r["unit"], "code": r["code"],
                         "signal_date": r["signal_date"].date(), "detail": f"占比 {r['share']:.1%}，分位 {r['share_pct']:.1%}",
                         "prediction": "未来 20/60 日相对市场跑输"})

    # R2
    ev = r2_events(P)
    rec2 = ev[ev["drop_date"] >= dates[max(0, n - int(c["nextday_avoid_days"]))]].copy()
    if not rec2.empty:
        def status(r):
            if pd.isna(r["next_ret"]):
                return "待次日确认"
            if r["next_ret"] < 0:
                end = dates.get_loc(r["confirm_date"]) + int(c["nextday_avoid_days"])
                return f"次日续跌 → 大概率不再创新高（观察至 {dates[end].date() if end < n else f'约 {end - n + 1} 个交易日后'}；不代表之后跑输）"
            return "次日收涨 → 仍有再创新高的机会"
        rec2["状态"] = rec2.apply(status, axis=1)
        rec2["行业"] = [P.data.name(k) for k in rec2["key"]]
    res.add("R2 强势行业 5%~7% 大跌（近 60 个交易日）", rec2[["行业", "drop_date", "drop_ret", "next_ret", "状态"]].rename(
        columns={"drop_date": "大跌日", "drop_ret": "跌幅", "next_ret": "次日涨跌"}) if not rec2.empty else rec2,
        "样本内（修正口径）：次日续跌时“趋势结束”（不再创新高且跑输）的比例高 18~29 个百分点，但之后的平均超额与次日收涨没有差别；跌幅 ≥7% 时不适用。", pct_cols=["跌幅", "次日涨跌"])
    for _, r in ev[(ev["drop_date"] >= oos_start) & ev["next_ret"].notna()].iterrows():
        grp = "续跌" if r["next_ret"] < 0 else "收涨"
        log_rows.append({"signal_id": f"R2|{r['key']}|{r['drop_date'].date()}", "rule": "R2", "unit": P.data.name(r["key"]), "code": r["key"],
                         "signal_date": r["drop_date"].date(), "detail": f"跌幅 {r['drop_ret']:.1%}，次日 {r['next_ret']:.1%}（{grp}）",
                         "prediction": "续跌组的趋势结束比例高于收涨组"})
    # 不适用的大跌
    strong_prev = ((P.rank60 <= c["strong_top_k"]) & (P.exc60 >= c["strong_min_exc60"])).shift(1, fill_value=False)
    big = (strong_prev & (P.ret <= -c["drop_hi"])).iloc[-20:]
    big_rows = [{"行业": P.data.name(k), "日期": d, "跌幅": P.ret.at[d, k]} for k in big.columns for d in big.index[big[k].to_numpy()]]
    if big_rows:
        res.add("强势行业 ≥7% 大跌（近 20 日，R2 不适用）", pd.DataFrame(big_rows), pct_cols=["跌幅"])

    # 主题成交占比
    grp_rows = []
    cc = P.cfg["common"]
    for g, members in P.data.valid_groups().items():
        s = P.data.group_amount(members) / P.data.total_amount
        p_ = R.rolling_percentile(s, cc["pct_window"], cc["pct_min_periods"])
        grp_rows.append({"主题": g, "当前占比": s.iloc[-1], "近20日最高": s.iloc[-20:].max(), "当前3年分位": p_.iloc[-1],
                         "历史最高": s.max(), "历史最高日期": s.idxmax()})
    res.add("主题成交占比", pd.DataFrame(grp_rows), "提醒：绝对阈值（30/40/45/50%）本身没有被证实能预测见顶。",
            pct_cols=["当前占比", "近20日最高", "当前3年分位", "历史最高"])

    # 主线状态
    ep = detect_episodes(P)
    if not ep.empty:
        on = ep[ep["状态"] != "完成"]
        res.add("进行中的主线（研究A，事后识别，仅描述）", on[["行业", "状态", "谷底", "首次超额", "拥挤", "相对顶部", "谷底→顶部超额"]],
                "“上涨中”的顶部尚未确认；“退潮中”的底部尚未确认。", pct_cols=["谷底→顶部超额"])

    # 市场环境
    labs = regime_labels(P)
    res.add("市场环境（研究F：实时划分滞后严重，仅作背景）", pd.DataFrame(
        [{"划分方法": k, "当前": v.dropna().iloc[-1] if v.notna().any() else ""} for k, v in labs.items() if "事后" not in k]))
    res.findings = [
        f"R1 回避名单：{recent['unit'].nunique() if len(recent) else 0} 个对象" + (f"（{'、'.join(pd.unique(recent['unit']))}）" if len(recent) else ""),
        f"R2 近 60 日适用大跌：{len(rec2)} 次" + (f"，其中次日续跌 {int((rec2['next_ret'] < 0).sum())} 次" if len(rec2) else ""),
        f"样本外起点 {oos_start.date()}；本次可记入样本外日志的信号 {len(log_rows)} 条。",
    ]
    log = pd.DataFrame(log_rows, columns=LOG_COLS[:-2])
    log["logged_asof"] = asof.date()
    log["logged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return res, log


def append_log(new: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=LOG_COLS)
    add = new[~new["signal_id"].isin(old["signal_id"])]
    pd.concat([old, add.astype(str)], ignore_index=True)[LOG_COLS].to_csv(path, index=False, encoding="utf-8-sig")
    return len(add)


def scoreboard(P: Panels, log_path: Path) -> StudyResult:
    from .studies.c_crash import END, NEUTRAL, OPP, add_features_outcomes
    o = P.cfg["oos"]
    cc = P.cfg["common"]
    res = StudyResult("S", "样本外计分板", "冻结规则在样本外（2026-10-01 起）的实际表现", meta=P.meta())
    log = pd.read_csv(log_path, dtype=str) if log_path.exists() else pd.DataFrame(columns=LOG_COLS)
    log = log[pd.to_datetime(log["signal_date"]) >= pd.Timestamp(o["start"])] if not log.empty else log
    res.definitions = [f"只统计信号日 ≥ {o['start']} 的信号；判定标准见 docs/rulebook.md",
                       f"R1 至少 {o['min_clusters_r1']} 个独立簇、R2 至少 {o['min_events_r2']} 个事件后才下结论"]
    if log.empty:
        res.findings.append("日志中还没有样本外信号。")
        _o3(P, res)
        return res
    dates = P.data.dates
    # R1
    r1 = log[log["rule"] == "R1"].copy()
    if not r1.empty:
        closes, _, _ = _units(P)
        rows = []
        for _, r in r1.iterrows():
            d = pd.Timestamp(r["signal_date"])
            if d not in dates or r["unit"] not in closes:
                continue
            row = {"对象": r["unit"], "信号日": d.date()}
            for h in (20, 60):
                f = R.excess(R.fwd_return(closes[[r["unit"]]], h, P.lag), R.fwd_return(P.data.market_close, h, P.lag))
                row[f"{h}日超额"] = f.at[d, r["unit"]]
            rows.append(row)
        t = pd.DataFrame(rows)
        res.add("R1 逐条结果", t, pct_cols=["20日超额", "60日超额"])
        done = t.dropna(subset=["60日超额"])
        if len(done):
            cl = stats.date_clusters(pd.to_datetime(done["信号日"]), 20, dates)
            x = done["60日超额"].to_numpy(dtype=float)
            cb = stats.cluster_bootstrap(lambda ix: float(np.mean(x[ix])), cl, n_boot=cc["n_boot"], rng=P.rng)
            k = cb["clusters"]
            verdict = (f"样本不足（{k}/{o['min_clusters_r1']} 个独立簇）" if k < o["min_clusters_r1"] else
                       "样本外确认" if (cb["stat"] < 0 and cb["hi"] < 0) else "样本外失效" if cb["stat"] > 0 else "方向一致但不显著")
            res.findings.append(f"R1：已到期 {len(done)} 条（{k} 个独立簇），60 日平均超额 {pct(cb['stat'])}（样本内 −2.0%）→ {verdict}。")
        else:
            res.findings.append(f"R1：{len(t)} 条信号尚未到期（需 60 个交易日）。")
    # R2
    r2 = log[log["rule"] == "R2"].copy()
    if not r2.empty:
        ev = pd.DataFrame({"date": pd.to_datetime(r2["signal_date"]), "key": r2["code"]})
        ev = ev[ev["date"].isin(dates)]
        if not ev.empty:
            out = add_features_outcomes(P, ev)
            out["次日"] = np.where(out["次日涨跌"] < 0, "续跌", "收涨")
            out["结果"] = out["结果(次日后)"]   # 规则手册 v1.1：结果从次日收盘之后计
            t = out[["行业", "date", "当日跌幅", "次日涨跌", "次日", "结果"]].rename(columns={"date": "大跌日"})
            res.add("R2 逐条结果", t, pct_cols=["当日跌幅", "次日涨跌"])
            done = out[out["结果"].isin([OPP, END, NEUTRAL])].reset_index(drop=True)
            if len(done):
                end = (done["结果"] == END).to_numpy(dtype=float)
                dn = (done["次日涨跌"] < 0).to_numpy()
                cl = stats.date_clusters(done["date"], 10, dates)

                def gap(ix):
                    a, b = end[ix][dn[ix]], end[ix][~dn[ix]]
                    return float(a.mean() - b.mean()) if len(a) >= 2 and len(b) >= 2 else np.nan

                cb = stats.cluster_bootstrap(gap, cl, n_boot=cc["n_boot"], rng=P.rng)
                verdict = (f"样本不足（{len(done)}/{o['min_events_r2']} 个事件）" if len(done) < o["min_events_r2"] else
                           "样本外确认" if (cb["stat"] > 0 and cb["lo"] > 0) else "样本外失效" if (cb["stat"] <= 0) else "方向一致但不显著")
                res.findings.append(f"R2：已到期 {len(done)} 个事件，结束比例差（续跌−收涨）{pct(cb['stat'], 0)}（样本内修正口径 +18~+29pp）→ {verdict}。")
            else:
                res.findings.append(f"R2：{len(ev)} 个事件尚未到期（需 60 个交易日）。")
    _o3(P, res)
    return res


def _o3(P: Panels, res: StudyResult) -> None:
    """观察项 O3：强势行业等权 − 全行业等权（样本外累计）。"""
    from .core import backtest as B
    from .studies.i_portfolio import eq_weights, strong_now
    o = P.cfg["oos"]
    oos = P.data.dates >= pd.Timestamp(o["start"])
    if oos.sum() <= 5:
        res.findings.append("O3（观察项）：尚无样本外数据。")
        return
    valid = P.data.sector_close.notna()
    reb = int(P.cfg["portfolio"]["rebalance_days"])
    w0 = B.hold_every(eq_weights(valid), reb)
    ws = B.hold_every(eq_weights(strong_now(P) & valid), reb)
    cost = P.cfg["portfolio"]["cost_bps"][0]
    d = (B.run_weights(ws, P.ret, P.lag, cost) - B.run_weights(w0, P.ret, P.lag, cost))[oos]
    res.findings.append(f"O3（观察项）：样本外 {len(d)} 个交易日，强势行业等权相对全行业等权累计 {pct(float((1 + d).prod() - 1))}（样本内年化约 −11%）。")
