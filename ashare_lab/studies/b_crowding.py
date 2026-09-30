"""研究B｜拥挤度：成交占比达到 30%/40%/45%/50% 之后，板块未来 5/10/20/60 日怎么样？

方法：
1. 对象：主题组合（TMT、周期、大消费……，由申万一级行业组成）的成交额占全A比重。
   单个一级行业几乎到不了 30%，所以单行业改用“自身历史分位”（90/95/99%）做相对阈值。
2. 事件 = 占比向上穿越阈值（回落到阈值-5pp 以下才重新计数、同一组合事件间隔 ≥20 日）。
   同一轮行情里连续多天高于阈值只算一次——否则样本数是假的。
3. 结果变量：未来 h 日的绝对收益、相对中证全指的超额、持有期最大浮亏、占比变化。
4. 对照：同一组合的“随机交易日”（置换检验）；以及“同样强势但不拥挤”的日子（区分拥挤效应和动量效应）。
5. 所有阈值×期限放在同一个检验族里做 BH 多重检验校正，并检查前后两段是否同向。
6. 如果有个股数据，额外检验“成交额前5%个股占比”（成交集中度）这一口径。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import returns as R
from ..core.events import concat_events, crossing_events, dwell_days, events_frame, restrict_dates
from ..core.eventstudy import add_grades, event_study, lookup
from ..report import StudyResult, pct
from .common import Panels


def unit_panels(P: Panels) -> tuple[pd.DataFrame, pd.DataFrame]:
    """主题组合的收盘指数与成交占比（宽表）。"""
    closes, shares = {}, {}
    for g, members in P.data.valid_groups().items():
        closes[g] = P.data.group_close(members)
        shares[g] = P.data.group_amount(members) / P.data.total_amount
    return pd.DataFrame(closes), pd.DataFrame(shares)


def _fwd_metrics(close: pd.DataFrame, market: pd.Series, share: pd.DataFrame, horizons, lag) -> dict[int, dict[str, pd.DataFrame]]:
    out = {}
    for h in horizons:
        fr = R.fwd_return(close, h, lag)
        out[h] = {
            f"未来{h}日收益": fr,
            f"未来{h}日超额": R.excess(fr, R.fwd_return(market, h, lag)),
            f"未来{h}日最大回撤": R.fwd_min_return(close, h, lag),
            f"未来{h}日占比变化": share.shift(-(h + lag)) - share,
        }
    return out


def _strong_not_crowded(close: pd.DataFrame, market: pd.Series, share: pd.DataFrame, max_share: float, cfg) -> pd.DataFrame:
    """对照组：20日超额处于自身历史前 20%，但占比低于最低阈值。"""
    exc20 = R.excess(R.past_return(close, 20), R.past_return(market, 20))
    c = cfg["common"]
    p = R.rolling_percentile_frame(exc20, c["pct_window"], c["pct_min_periods"])
    return (p >= 0.8) & (share < max_share)


def _events_abs(share: pd.DataFrame, thresholds, gap, min_gap) -> pd.DataFrame:
    frames = []
    for th in thresholds:
        per = {g: crossing_events(share[g], th, rearm=th - gap, min_gap=min_gap) for g in share.columns}
        ev = events_frame(per, 阈值=th)
        frames.append(ev)
    return concat_events(frames, ["date", "key", "阈值"])


def _study_family(P: Panels, events: pd.DataFrame, fwd: dict, horizons, eligible=None, label_col="阈值") -> pd.DataFrame:
    rows = []
    for th, ev in events.groupby(label_col, sort=True):
        ev = ev[["date", "key"]].reset_index(drop=True)
        for h in horizons:
            metrics = {f"未来{h}日超额": fwd[h][f"未来{h}日超额"]}
            t = event_study(ev, metrics, eligible, P.split, P.cfg["common"]["n_perm"], P.cfg["common"]["n_boot"], P.rng,
                            period=P.period)
            t.insert(0, label_col, th)
            t.insert(1, "期限", h)
            # 附加描述性指标（不进检验族）
            for extra in (f"未来{h}日收益", f"未来{h}日最大回撤"):
                v = lookup(fwd[h][extra], ev)
                t[extra.replace(f"未来{h}日", "") + "均值"] = np.nanmean(v) if np.isfinite(v).any() else np.nan
            rows.append(t)
    if not rows:
        return pd.DataFrame()
    return add_grades(pd.concat(rows, ignore_index=True), P.grade_rule)


def run(P: Panels) -> StudyResult:
    c = P.cfg["crowding"]
    cc = P.cfg["common"]
    res = StudyResult("B", "拥挤度", "成交占比达到 30%/40%/45%/50% 以后，板块未来 5/10/20/60 日到底怎么样？", meta=P.meta())
    res.definitions = [
        "成交占比 = 组合内行业成交额之和 / 全部申万一级行业成交额之和（口径一致，近似全A成交额）",
        "组合指数 = 成员行业日收益等权合成",
        f"事件 = 占比向上穿越阈值；回落到“阈值−{c['rearm_gap']:.0%}”以下才重新计数；同一组合两次事件间隔 ≥ {c['min_gap_days']} 个交易日",
        f"单行业相对阈值 = 成交占比处于自身过去 {cc['pct_window']} 日的 {'/'.join(f'{x:.0%}' for x in c['rel_pct_thresholds'])} 分位",
        "对照1（平常日子）：同一组合研究区间内的全部交易日；p 值来自“整体时间平移”置换检验（保留事件扎堆结构，偏保守）",
        "对照2（强势不拥挤）：20日超额处于自身历史前20%，但占比低于最低阈值的日子",
        "超额 = 组合收益 − 中证全指收益",
    ]
    horizons = P.horizons
    closes, shares = unit_panels(P)
    if closes.empty:
        res.findings.append("配置里的主题组合与数据中的行业代码对不上，无法计算组合成交占比。")
        return res
    fwd = _fwd_metrics(closes, P.data.market_close, shares, horizons, P.lag)

    # ---- 1. 绝对阈值（主题组合）----
    ev_abs = restrict_dates(_events_abs(shares, c["abs_thresholds"], c["rearm_gap"], c["min_gap_days"]), P.study_start, P.study_end)
    fam = _study_family(P, ev_abs, fwd, horizons)
    snc = _strong_not_crowded(closes, P.data.market_close, shares, min(c["abs_thresholds"]), P.cfg)
    if not fam.empty:
        # 对照2：以“强势不拥挤”的日子为随机池再做一次置换检验（补充检验，不进 BH 检验族）
        ctrl_mean, ctrl_diff, ctrl_p = [], [], []
        for _, row in fam.iterrows():
            ev = ev_abs[ev_abs["阈值"] == row["阈值"]][["date", "key"]].reset_index(drop=True)
            h = row["期限"]
            t = event_study(ev, {"x": fwd[h][f"未来{h}日超额"]}, snc, P.split, cc["n_perm"], cc["n_boot"], P.rng,
                            period=P.period).iloc[0]
            ctrl_mean.append(t["基准均值"])
            ctrl_diff.append(t["差值"])
            ctrl_p.append(t["p值"])
        fam.insert(fam.columns.get_loc("基准均值") + 1, "强势不拥挤均值", ctrl_mean)
        fam["对强势不拥挤差值"] = ctrl_diff
        fam["对强势不拥挤p值"] = ctrl_p

    # 占比最高水平 & 各组合历史分布
    dist_rows = []
    for g in shares.columns:
        s = shares[g][P.in_study(shares.index)].dropna()
        if s.empty:
            continue
        row = {"组合": g, "成员": "、".join(P.data.name(x) for x in P.data.valid_groups()[g]),
               "占比中位": s.median(), "占比P90": s.quantile(0.9), "历史最高": s.max(), "最高日期": s.idxmax()}
        for th in c["abs_thresholds"]:
            row[f"≥{th:.0%}天数"] = int((s >= th).sum())
        dist_rows.append(row)
    dist = pd.DataFrame(dist_rows)
    dist_pct = ["占比中位", "占比P90", "历史最高"]

    # 事件明细
    detail = ev_abs.copy()
    if not detail.empty:
        detail["组合"] = detail["key"]
        detail["触发日占比"] = [shares.at[d, k] for d, k in zip(detail["date"], detail["key"])]
        for h in horizons:
            detail[f"{h}日超额"] = lookup(fwd[h][f"未来{h}日超额"], detail)
        detail["60日最大回撤"] = lookup(fwd[max(horizons)][f"未来{max(horizons)}日最大回撤"], detail) if max(horizons) in fwd else np.nan
        detail["阈值上方停留(日)"] = [dwell_days(shares[k], d, th - c["rearm_gap"]) for d, k, th in zip(detail["date"], detail["key"], detail["阈值"])]
        detail = detail.rename(columns={"date": "触发日"}).drop(columns=["key"])
        detail = detail[["阈值", "组合", "触发日", "触发日占比", *[f"{h}日超额" for h in horizons], "60日最大回撤", "阈值上方停留(日)"]]

    # ---- 2. 相对阈值（组合 + 单行业）----
    rel_units_close = closes.copy()
    rel_units_share = shares.copy()
    if c.get("include_single_sectors", True):
        for code in P.data.sector_close.columns:
            rel_units_close[P.data.name(code)] = P.data.sector_close[code]
            rel_units_share[P.data.name(code)] = P.share[code]
    rel_units_close = rel_units_close.loc[:, ~rel_units_close.columns.duplicated()]
    rel_units_share = rel_units_share.loc[:, ~rel_units_share.columns.duplicated()]
    share_pct = R.rolling_percentile_frame(rel_units_share, cc["pct_window"], cc["pct_min_periods"])
    fwd_rel = _fwd_metrics(rel_units_close, P.data.market_close, rel_units_share, horizons, P.lag)
    frames = []
    for q in c["rel_pct_thresholds"]:
        per = {u: crossing_events(share_pct[u], q, rearm=q - c["rel_rearm_gap"], min_gap=c["min_gap_days"]) for u in share_pct.columns}
        frames.append(events_frame(per, 阈值=q))
    ev_rel = restrict_dates(concat_events(frames, ["date", "key", "阈值"]), P.study_start, P.study_end)
    fam_rel = _study_family(P, ev_rel, fwd_rel, horizons)
    if not fam_rel.empty:
        fam_rel = fam_rel.rename(columns={"阈值": "分位阈值"})

    # ---- 3. 个股成交集中度（可选）----
    conc_tbl = None
    if P.data.stocks is not None:
        conc_tbl, conc_series = _concentration(P, horizons)
        if conc_series is not None:
            res.add("成交集中度（前5%个股成交占比）走势摘要", pd.DataFrame([{
                "中位": conc_series.median(), "P90": conc_series.quantile(0.9), "最高": conc_series.max(),
                "最高日期": conc_series.idxmax()}]), pct_cols=["中位", "P90", "最高"])

    # ---- 输出 ----
    show = ["阈值", "期限", "n", "独立簇", "均值", "中位数", "胜率", "基准均值", "强势不拥挤均值", "差值", "均值90%CI低", "均值90%CI高",
            "p值", "q值", "前段n", "后段n", "两段同向", "证据", "对强势不拥挤差值", "对强势不拥挤p值", "收益均值", "最大回撤均值"]
    res.add("各组合成交占比的历史分布", dist, "先看清楚每个阈值历史上到底出现过几次。", pct_cols=dist_pct)
    if not fam.empty:
        res.add("绝对阈值：穿越后未来超额（主题组合合并）", fam[[c_ for c_ in show if c_ in fam.columns]],
                "“差值”= 事件均值 − 同组合平常日子均值；p 值为整体时间平移置换检验；q 值为全表 BH 校正；"
                "独立簇 = 相隔 ≤20 个交易日的事件（不论哪个组合）归为一簇，证据等级按簇数计。")
    res.add("绝对阈值事件明细", detail if not detail.empty else pd.DataFrame(),
            "逐个列出每次触发——样本少的时候，看明细比看均值更诚实。")
    if not fam_rel.empty:
        show_rel = ["分位阈值", "期限", "n", "独立簇", "均值", "中位数", "胜率", "基准均值", "差值", "均值90%CI低", "均值90%CI高",
                    "p值", "q值", "两段同向", "证据", "收益均值", "最大回撤均值"]
        res.add("相对阈值：占比创自身历史高分位后（组合+单行业合并）", fam_rel[show_rel])
    if conc_tbl is not None and not conc_tbl.empty:
        res.add("成交集中度阈值：穿越后全市场未来收益", conc_tbl)

    # ---- 结论 ----
    for th in c["abs_thresholds"]:
        sub = fam[fam["阈值"] == th] if not fam.empty else pd.DataFrame()
        if sub.empty:
            res.findings.append(f"占比 {th:.0%}：研究区间内没有任何主题组合穿越过该阈值，无法检验。")
            continue
        n = int(sub["n"].max())
        ncl = int(sub["独立簇"].max())
        parts = []
        for _, r in sub.iterrows():
            parts.append(f"{r['期限']}日超额均值 {pct(r['均值'])}（随机日 {pct(r['基准均值'])}，胜率 {pct(r['胜率'], 0)}，{r['证据']}）")
        res.findings.append(f"占比 {th:.0%}（事件 {n} 次，按时间归并为 {ncl} 个独立簇）：" + "；".join(parts) + "。")
    if not fam.empty:
        best = fam[fam["证据"].str.startswith(("A", "B"))]
        if best.empty:
            res.findings.append("绝对阈值检验族中没有任何一项达到 B 级以上证据——“成交占比到 X% 就见顶/就要跌”在这段样本里**没有被统计证实**，"
                                "只能作为风险提示，不能作为确定的择时规则。")
        else:
            for _, r in best.iterrows():
                direction = "显著偏弱" if r["差值"] < 0 else "显著偏强"
                res.findings.append(f"占比 {r['阈值']:.0%}、{r['期限']}日：相对随机日{direction}（差值 {pct(r['差值'])}，q={r['q值']:.3f}，{r['证据']}）。")
        for _, r in fam[(fam["期限"] == max(horizons)) & (fam["独立簇"] >= P.grade_rule.min_n)].iterrows():
            res.findings.append(
                f"占比 {r['阈值']:.0%} vs “强势但不拥挤”：{r['期限']}日超额 {pct(r['均值'])} 对 {pct(r['强势不拥挤均值'])}"
                f"（差值 {pct(r['对强势不拥挤差值'])}，p={r['对强势不拥挤p值']:.3f}）——这个差才是“拥挤”本身的影响，而不是动量的影响。"
            )
    if not fam_rel.empty:
        sig = fam_rel[fam_rel["证据"].str.startswith(("A", "B"))]
        res.findings.append(
            f"相对阈值（组合+单行业，{len(fam_rel)} 项检验）中达到 B 级以上的有 {len(sig)} 项"
            + ("：" + "；".join(f"{r['分位阈值']:.0%}分位/{r['期限']}日 差值{pct(r['差值'])}" for _, r in sig.iterrows()) if len(sig) else "。")
        )
    res.caveats = [
        "成交占比的“历史最高”随市场结构变化：2015年后 TMT 扩容、2019年后科创板/创业板注册制扩容都会抬高电子等行业的常态占比。",
        "高阈值（45%/50%）在十年里往往只有 1~3 次独立事件，任何统计量都不可靠——报告里标为 D 级，只看明细。",
        "组合指数采用成员行业等权，与市值加权的真实组合有差别；可以在 data 里提供组合指数替换。",
        "申万一级之和作为全A成交额的近似，北交所、B股等未覆盖部分影响很小。",
    ]
    return res


def _concentration(P: Panels, horizons) -> tuple[pd.DataFrame | None, pd.Series | None]:
    c = P.cfg["crowding"]
    st = P.data.stocks
    top = c["concentration_top"]

    def conc(g: pd.DataFrame) -> float:
        a = np.sort(g["amount"].to_numpy(dtype=float))[::-1]
        a = a[np.isfinite(a)]
        if len(a) < 50:
            return np.nan
        k = max(1, int(round(len(a) * top)))
        return a[:k].sum() / a.sum()

    series = st.groupby("date")[["amount"]].apply(conc).reindex(P.data.dates)
    series.name = "集中度"
    if series.notna().sum() < 100:
        return None, None
    close = P.data.market_close.to_frame("全A")
    share = series.to_frame("全A")
    fwd = _fwd_metrics(close, P.data.market_close * 0 + 1, share, horizons, P.lag)
    # 市场自身的绝对收益（超额 = 相对常数 1 → 就是绝对收益）
    frames = []
    for th in c["concentration_thresholds"]:
        per = {"全A": crossing_events(series, th, rearm=th - c["rearm_gap"], min_gap=c["min_gap_days"])}
        frames.append(events_frame(per, 阈值=th))
    ev = restrict_dates(concat_events(frames, ["date", "key", "阈值"]), P.study_start, P.study_end)
    if ev.empty:
        return pd.DataFrame(), series
    tbl = _study_family(P, ev, fwd, horizons)
    tbl = tbl.drop(columns=[c_ for c_ in ("收益均值",) if c_ in tbl])
    tbl = tbl.rename(columns={"均值": "全A收益均值"})
    return tbl, series
