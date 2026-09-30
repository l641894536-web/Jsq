"""研究I｜把规律做成组合：扣成本后还有没有经济意义？

规则（定义冻结在 docs/rulebook.md）：
- R1 拥挤回避：行业成交占比创自身 3 年 99% 分位后，回避 60 个交易日；
- R2 次日确认：强势行业单日跌 5%~7% 且次日续跌，回避 60 个交易日。

组合（每 5 个交易日调仓，信号 t 日收盘确认、t+entry_lag 日收盘成交，扣单边成本）：
- B0 全部行业等权；P1 = B0 剔除 R1 回避名单（其余等权）；
- S0 强势行业等权；S1 = S0 剔除 R2 回避名单，被剔除的权重转投 B0（保持总仓位一致，只比较“选哪些行业”）。

注意：R1、R2 是在同一段样本上发现的，本研究只检验可交易性（扣成本、换手、逐年稳定性），不是独立验证。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import backtest as B
from ..core import returns as R
from ..core import stats
from ..core.events import crossing_events
from ..report import StudyResult, pct
from .common import Panels


def r1_blacklist(P: Panels) -> tuple[pd.DataFrame, pd.DataFrame]:
    """R1：返回 (事件矩阵, 回避名单)，均为 日期×行业 布尔宽表。"""
    c = P.cfg["portfolio"]
    ev = pd.DataFrame(False, index=P.data.dates, columns=P.data.sector_close.columns)
    for code in ev.columns:
        d = crossing_events(P.share_pct[code], c["crowd_pct"], rearm=c["crowd_pct"] - 0.10,
                            min_gap=P.cfg["crowding"]["min_gap_days"])
        ev.loc[d, code] = True
    black = ev.astype(float).rolling(int(c["avoid_days"]), min_periods=1).sum() > 0
    return ev, black


def strong_now(P: Panels) -> pd.DataFrame:
    c = P.cfg["portfolio"]
    return (P.rank60 <= c["strong_top_k"]) & (P.exc60 >= c["strong_min_exc60"])


def r2_events(P: Panels) -> pd.DataFrame:
    """R2 适用的大跌事件：前一日强势、当日跌幅在 [drop_lo, drop_hi)。返回 DataFrame[drop_date, key, next_ret, confirm_date]。"""
    c = P.cfg["portfolio"]
    ret = P.ret
    strong_prev = strong_now(P).shift(1, fill_value=False)
    hit = strong_prev & (ret <= -c["drop_lo"]) & (ret > -c["drop_hi"])
    dates = P.data.dates
    rows = []
    for code in hit.columns:
        for i in np.flatnonzero(hit[code].to_numpy()):
            nxt = ret[code].iloc[i + 1] if i + 1 < len(dates) else np.nan
            rows.append({"drop_date": dates[i], "key": code, "drop_ret": ret[code].iloc[i], "next_ret": nxt,
                         "confirm_date": dates[i + 1] if i + 1 < len(dates) else pd.NaT})
    return pd.DataFrame(rows, columns=["drop_date", "key", "drop_ret", "next_ret", "confirm_date"])


def r2_blacklist(P: Panels, ev: pd.DataFrame) -> pd.DataFrame:
    c = P.cfg["portfolio"]
    m = pd.DataFrame(False, index=P.data.dates, columns=P.data.sector_close.columns)
    for d, k, nr in zip(ev["confirm_date"], ev["key"], ev["next_ret"]):
        if pd.notna(d) and np.isfinite(nr) and nr < 0:
            m.at[d, k] = True
    return m.astype(float).rolling(int(c["nextday_avoid_days"]), min_periods=1).sum() > 0


def eq_weights(mask: pd.DataFrame) -> pd.DataFrame:
    w = mask.astype(float)
    return w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def diff_stats(d: pd.Series, split, block: int, n_boot: int, rng) -> dict:
    d = d.dropna()
    ann = d.mean() * B.TRADING_DAYS
    lo90, hi90 = stats.block_bootstrap_mean_ci(d.to_numpy(), block=block, n_boot=n_boot, alpha=0.10, rng=rng)
    lo95, hi95 = stats.block_bootstrap_mean_ci(d.to_numpy(), block=block, n_boot=n_boot, alpha=0.05, rng=rng)
    a1 = d[d.index <= split].mean() * B.TRADING_DAYS
    a2 = d[d.index > split].mean() * B.TRADING_DAYS
    cons = bool(np.isfinite(a1) and np.isfinite(a2) and a1 * a2 > 0)
    yrs = d.groupby(d.index.year).sum()
    grade = ("A 强证据" if cons and (lo95 > 0 or hi95 < 0) else
             "B 中等证据" if cons and (lo90 > 0 or hi90 < 0) else "C 弱/不显著")
    return {"年化超额": ann, "90%CI低": lo90 * B.TRADING_DAYS, "90%CI高": hi90 * B.TRADING_DAYS,
            "信息比率": d.mean() / d.std() * np.sqrt(B.TRADING_DAYS) if d.std() > 0 else np.nan,
            "前段年化": a1, "后段年化": a2, "两段同向": cons,
            "跑赢年份": f"{int((yrs > 0).sum())}/{len(yrs)}", "证据": grade}


def turnover(w: pd.DataFrame) -> float:
    return float(w.diff().abs().sum(axis=1).mean() * B.TRADING_DAYS / 2)


def run(P: Panels) -> StudyResult:
    c = P.cfg["portfolio"]
    cc = P.cfg["common"]
    res = StudyResult("I", "规律组合", "两条 A 级规律做成行业组合后，扣交易成本还有没有经济意义？", meta=P.meta())
    res.definitions = [
        f"R1 拥挤回避：行业成交占比向上穿越自身 3 年 {c['crowd_pct']:.0%} 分位后回避 {c['avoid_days']} 个交易日",
        f"R2 次日确认：前一日强势（60 日超额排名前 {c['strong_top_k']} 且 ≥{c['strong_min_exc60']:.0%}）的行业单日跌幅在 "
        f"[{c['drop_lo']:.0%}, {c['drop_hi']:.0%})，次日续跌 → 回避 {c['nextday_avoid_days']} 个交易日",
        "B0 全部行业等权；P1 = B0 剔除 R1 名单（其余等权）；S0 强势行业等权；S1 = S0 剔除 R2 名单，被剔除的权重转投 B0",
        f"每 {c['rebalance_days']} 个交易日调仓；信号 t 日收盘确认、t+{P.lag} 日收盘成交；单边成本 {'/'.join(str(x) for x in c['cost_bps'])}bp",
        f"差值检验：移动块自助法（{c['block']} 日块）；A=95%CI 不含 0 且前后两段同向，B=90%CI 不含 0 且同向",
        "这两条规律来自同一段样本，本研究只检验可交易性，不是独立验证；独立验证见样本外跟踪（scoreboard）",
    ]
    sec_ret = P.ret
    valid = P.data.sector_close.notna()
    ev1, black1 = r1_blacklist(P)
    ev2 = r2_events(P)
    black2 = r2_blacklist(P, ev2)
    strong = strong_now(P) & valid

    w_b0 = eq_weights(valid)
    w_p1 = eq_weights(valid & ~black1)
    w_s0 = eq_weights(strong)
    keep = strong & ~black2
    w_s1_core = eq_weights(keep) * (keep.sum(axis=1) / strong.sum(axis=1).replace(0, np.nan)).fillna(0.0).to_numpy()[:, None]
    freed = (1 - w_s1_core.sum(axis=1)).where(strong.sum(axis=1) > 0, 0.0)
    w_s1 = w_s1_core + w_b0.mul(freed, axis=0)
    w_crowd = eq_weights(valid & black1)
    weights = {"B0 全行业等权": w_b0, "P1 剔除拥挤(R1)": w_p1, "S0 强势行业等权": w_s0,
               "S1 强势剔除次日续跌(R2)": w_s1, "拥挤篮子(被R1剔除的行业)": w_crowd}
    weights = {k: B.hold_every(v, int(c["rebalance_days"])) for k, v in weights.items()}

    study = P.in_study(P.data.dates)
    perf_rows, test_rows, yearly = [], [], {}
    for cost in c["cost_bps"]:
        rets = {k: B.run_weights(w, sec_ret, P.lag, cost)[study] for k, w in weights.items()}
        # 拥挤篮子只在名单非空的日子有意义
        has_crowd = (weights["拥挤篮子(被R1剔除的行业)"].shift(1 + P.lag).sum(axis=1) > 0)[study]
        for k, r in rets.items():
            rr = r[has_crowd] if k.startswith("拥挤篮子") else r
            perf_rows.append({"成本(bp)": cost, "组合": k, **B.perf_stats(rr), "年化单边换手": turnover(weights[k][study])})
        pairs = [("H-I1 R1：P1 − B0", rets["P1 剔除拥挤(R1)"] - rets["B0 全行业等权"]),
                 ("H-I2 R2：S1 − S0", rets["S1 强势剔除次日续跌(R2)"] - rets["S0 强势行业等权"]),
                 ("参考：拥挤篮子 − B0（名单非空的日子）", (rets["拥挤篮子(被R1剔除的行业)"] - rets["B0 全行业等权"])[has_crowd])]
        for name, d in pairs:
            test_rows.append({"成本(bp)": cost, "比较": name, **diff_stats(d, P.split, int(c["block"]), cc["n_boot"], P.rng)})
            if cost == c["cost_bps"][0]:
                yearly[name] = d.groupby(d.index.year).sum()
    perf = pd.DataFrame(perf_rows)
    tests = pd.DataFrame(test_rows)
    yr = pd.DataFrame(yearly)
    yr.index.name = "年份"

    # H-I3：事件层面（次日收盘确认后入场）
    ev2s = ev2[(ev2["drop_date"] >= P.study_start) & ev2["next_ret"].notna()].reset_index(drop=True)
    ev_rows = []
    if len(ev2s) >= 10:
        down = (ev2s["next_ret"] < 0).to_numpy()
        cl = stats.date_clusters(ev2s["drop_date"], 10, P.data.dates)
        for h in c["event_horizons"]:
            fwd = P.fwd_exc(h)   # 从 t+lag 收盘起算；这里的 t 取确认日（次日）
            y = np.array([fwd.at[d, k] if pd.notna(d) and d in fwd.index else np.nan
                          for d, k in zip(ev2s["confirm_date"], ev2s["key"])])
            ok = np.isfinite(y)

            def gap(ix, y=y, ok=ok):
                ix = ix[ok[ix]]
                a, b = y[ix][down[ix]], y[ix][~down[ix]]
                return float(a.mean() - b.mean()) if len(a) >= 2 and len(b) >= 2 else np.nan

            cb = stats.cluster_bootstrap(gap, cl, n_boot=cc["n_boot"], rng=P.rng)
            first = (ev2s["drop_date"] <= P.split).to_numpy()
            g1 = gap(np.flatnonzero(first))
            g2 = gap(np.flatnonzero(~first))
            cons = bool(np.isfinite(g1) and np.isfinite(g2) and g1 * g2 > 0)
            ev_rows.append({"期限": h, "事件数": int(ok.sum()), "次日续跌组": int((ok & down).sum()), "次日收涨组": int((ok & ~down).sum()),
                            "续跌组超额均值": np.nanmean(y[ok & down]), "收涨组超额均值": np.nanmean(y[ok & ~down]),
                            "差值(续跌−收涨)": cb["stat"], "90%CI低": cb["lo"], "90%CI高": cb["hi"], "p值": cb["p"],
                            "独立簇": cb["clusters"], "前段差": g1, "后段差": g2, "两段同向": cons})
    evt = pd.DataFrame(ev_rows)
    if not evt.empty:
        evt["q值"] = stats.bh_adjust(evt["p值"].to_numpy())
        evt["证据"] = [stats.GRADE_TEXT[stats.evidence_grade(int(n), q, cs, P.grade_rule)]
                      for n, q, cs in zip(evt["独立簇"], evt["q值"], evt["两段同向"])]

    # ---- 诊断（看过 H-I2/H-I3 结果后添加）：安慰剂 —— 换成“次日收涨就剔除”“大跌就剔除”是否一样有效 ----
    def s1_from(sel):
        m = pd.DataFrame(False, index=P.data.dates, columns=P.data.sector_close.columns)
        for d, k, nr in zip(ev2["confirm_date"], ev2["key"], ev2["next_ret"]):
            if pd.notna(d) and np.isfinite(nr) and sel(nr):
                m.at[d, k] = True
        bl = m.astype(float).rolling(int(c["nextday_avoid_days"]), min_periods=1).sum() > 0
        kp = strong & ~bl
        core = eq_weights(kp) * (kp.sum(axis=1) / strong.sum(axis=1).replace(0, np.nan)).fillna(0.0).to_numpy()[:, None]
        fr = (1 - core.sum(axis=1)).where(strong.sum(axis=1) > 0, 0.0)
        return B.hold_every(core + w_b0.mul(fr, axis=0), int(c["rebalance_days"]))

    main_cost = c["cost_bps"][0]
    r_s0 = B.run_weights(weights["S0 强势行业等权"], sec_ret, P.lag, main_cost)[study]
    r_b0 = B.run_weights(weights["B0 全行业等权"], sec_ret, P.lag, main_cost)[study]
    pl_rows = []
    for lab_, sel in (("R2：次日续跌就剔除", lambda x: x < 0), ("安慰剂：次日收涨就剔除", lambda x: x >= 0),
                      ("安慰剂：大跌就剔除（不看次日）", lambda x: True)):
        d_ = B.run_weights(s1_from(sel), sec_ret, P.lag, main_cost)[study] - r_s0
        pl_rows.append({"规则": lab_, **diff_stats(d_, P.split, int(c["block"]), cc["n_boot"], P.rng)})
    s0b0 = diff_stats(r_s0 - r_b0, P.split, int(c["block"]), cc["n_boot"], P.rng)
    pl_rows.append({"规则": "参考：S0 强势行业等权 − B0 全行业等权", **s0b0})
    placebo = pd.DataFrame(pl_rows)

    # ---- 表格 ----
    res.add("H-I1 / H-I2：规则组合相对基准的超额", tests,
            pct_cols=["年化超额", "90%CI低", "90%CI高", "前段年化", "后段年化"])
    res.add("各组合表现", perf, pct_cols=["年化收益", "年化波动", "最大回撤", "日胜率", "年化单边换手"])
    res.add(f"逐年超额（单边成本 {c['cost_bps'][0]}bp）", yr.reset_index(), pct_cols=list(yr.columns))
    if not evt.empty:
        res.add("H-I3：5%~7% 大跌后，次日收盘确认再入场的未来超额", evt,
                pct_cols=["续跌组超额均值", "收涨组超额均值", "差值(续跌−收涨)", "90%CI低", "90%CI高", "前段差", "后段差"])
    res.add(f"诊断（看过结果后添加）：安慰剂对照（S1 − S0，单边 {main_cost}bp）", placebo,
            "如果“次日收涨就剔除”或“大跌就剔除”也能带来差不多的超额，说明 S1 的超额不是来自次日确认本身。",
            pct_cols=["年化超额", "90%CI低", "90%CI高", "前段年化", "后段年化"])
    n_r1 = int(ev1.loc[study].sum().sum())
    res.add("规则触发次数（研究区间）", pd.DataFrame([
        {"规则": "R1 拥挤事件", "次数": n_r1, "平均每天回避的行业数": float(black1.loc[study].sum(axis=1).mean())},
        {"规则": "R2 适用大跌（5%~7%）", "次数": len(ev2s), "平均每天回避的行业数": float(black2.loc[study].sum(axis=1).mean())},
        {"规则": "R2 其中次日续跌", "次数": int((ev2s["next_ret"] < 0).sum()), "平均每天回避的行业数": np.nan},
    ]), pct_cols=[])

    # ---- 结论 ----
    for name in ("H-I1 R1：P1 − B0", "H-I2 R2：S1 − S0"):
        r = tests[(tests["比较"] == name) & (tests["成本(bp)"] == main_cost)].iloc[0]
        r30 = tests[(tests["比较"] == name) & (tests["成本(bp)"] == c["cost_bps"][-1])].iloc[0]
        res.findings.append(
            f"{name}：扣 {main_cost}bp 后年化超额 {pct(r['年化超额'])}（90%CI {pct(r['90%CI低'])}~{pct(r['90%CI高'])}，"
            f"信息比率 {r['信息比率']:.2f}，前段 {pct(r['前段年化'])}/后段 {pct(r['后段年化'])}，跑赢年份 {r['跑赢年份']}，{r['证据']}）；"
            f"扣 {c['cost_bps'][-1]}bp 后 {pct(r30['年化超额'])}（{r30['证据']}）。"
        )
    r = tests[(tests["比较"].str.startswith("参考")) & (tests["成本(bp)"] == main_cost)].iloc[0]
    res.findings.append(f"拥挤篮子本身（被 R1 剔除的行业）相对全行业等权年化 {pct(r['年化超额'])}（{r['证据']}）。")
    pr = placebo.set_index("规则")
    res.findings.append(
        f"安慰剂诊断：次日续跌剔除 {pct(pr.iloc[0]['年化超额'])}，次日收涨剔除 {pct(pr.iloc[1]['年化超额'])}，不看次日直接剔除 "
        f"{pct(pr.iloc[2]['年化超额'])}——若三者相近，S1 的超额来自“离开大跌后的强势行业”，而不是次日确认。"
        f"参考：强势行业等权组合本身相对全行业等权年化 {pct(s0b0['年化超额'])}（{s0b0['证据']}）。"
    )
    if not evt.empty:
        for _, r in evt.iterrows():
            res.findings.append(
                f"H-I3 {int(r['期限'])} 日：次日续跌组 {pct(r['续跌组超额均值'])} vs 收涨组 {pct(r['收涨组超额均值'])}，"
                f"差 {pct(r['差值(续跌−收涨)'])}（90%CI {pct(r['90%CI低'])}~{pct(r['90%CI高'])}，{r['证据']}）。"
            )
    res.caveats = [
        "目标权重在两次调仓之间保持不变（忽略权重漂移），成本只按目标权重变化计算。",
        "行业指数无法直接交易；现实中用行业 ETF 或一篮子个股，还会有跟踪误差与冲击成本。",
        "规则参数来自同一段样本的前两轮研究，所以这里的表现偏乐观；以样本外跟踪为准。",
    ]
    return res
