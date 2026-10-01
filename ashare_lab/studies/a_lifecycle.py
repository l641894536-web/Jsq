"""研究A｜主线生命周期。

问题：2015—2026 每轮主线从第一次超额收益出现，到加速、拥挤、顶部、退潮到底分别多长时间？
能不能用“时间”来判断主线走到了哪个阶段？

方法：
1. 主线 = 行业相对强弱线 RS（行业/中证全指）上的一段大级别上涨：
   zigzag(20%) 找峰谷，谷→峰超额 ≥ 30%、≥ 20 个交易日，且期间 60 日超额排名进过前 3。
2. 阶段节点（除“顶部/底部”外都是 t 日可观测的）：
   谷底 T0（事后）→ 首次超额（20日超额首次≥5%）→ 加速（20日超额首次≥15%）
   → 拥挤（成交占比首次到自身3年95%分位）→ 相对顶部 P（事后）→ 退潮底部 B（事后）。
3. 只用“已完成”的阶段统计时长（右截断的进行中样本单列），报告中位数和四分位距；
   离散度 = IQR/中位数，> 1 说明“按天数判断阶段”基本不可用。
4. 可交易视角：看到首次超额/加速/拥挤信号那天起，到顶部还剩多少天、多少超额，
   以及如果一直拿到退潮底部，最后是赚是亏。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import stats
from ..core.zigzag import zigzag
from ..report import StudyResult, num, pct
from .common import Panels, first_true

STAGES = ["首次超额", "加速", "拥挤"]


def detect_episodes(P: Panels) -> pd.DataFrame:
    c = P.cfg["lifecycle"]
    dates = P.data.dates
    n = len(dates)
    rs = P.rs
    exc20 = P.exc20.to_numpy()
    rank60 = P.rank60.to_numpy()
    share_pct = P.share_pct.to_numpy()
    close = P.data.sector_close.to_numpy()
    rows = []
    for j, code in enumerate(rs.columns):
        piv = zigzag(rs[code], c["rs_swing"])
        if len(piv) < 2:
            continue
        rsv = rs[code].to_numpy()
        first_valid = int(np.flatnonzero(np.isfinite(rsv))[0])
        for a in range(len(piv) - 1):
            if piv.at[a, "kind"] != "trough":
                continue
            b = a + 1
            t0, tp = int(piv.at[a, "pos"]), int(piv.at[b, "pos"])
            gain = rsv[tp] / rsv[t0] - 1
            if gain < c["min_excess"] or tp - t0 < c["min_days"]:
                continue
            if not np.nanmin(rank60[t0:tp + 1, j]) <= c["top_rank"]:
                continue
            peak_confirmed = bool(piv.at[b, "confirmed"])
            if b + 1 < len(piv):
                tb = int(piv.at[b + 1, "pos"])
                bottom_confirmed = bool(piv.at[b + 1, "confirmed"])
            else:
                tb, bottom_confirmed = n - 1, False
            t_start = first_true(exc20[:, j] >= c["start_excess_20d"], t0 + 1, tp)
            t_accel = first_true(exc20[:, j] >= c["accel_excess_20d"], t_start, tp) if t_start is not None else None
            t_crowd = first_true(share_pct[:, j] >= c["crowd_pct"], t_start, tb) if t_start is not None else None
            t_abs_peak = t0 + int(np.nanargmax(close[t0:tb + 1, j]))
            confirm_pos = int(piv.at[b, "confirm_pos"]) if peak_confirmed else None

            def d(p):
                return dates[p] if p is not None else pd.NaT

            def rs_ret(p_from, p_to):
                if p_from is None or p_to is None:
                    return np.nan
                return rsv[p_to] / rsv[p_from] - 1

            status = "完成" if (peak_confirmed and bottom_confirmed) else ("退潮中(底部未确认)" if peak_confirmed else "上涨中(顶部未确认)")
            rows.append({
                "行业": P.data.name(code), "代码": code, "状态": status,
                "左截断": t0 - first_valid < 60,
                "谷底": d(t0), "首次超额": d(t_start), "加速": d(t_accel), "拥挤": d(t_crowd),
                "相对顶部": d(tp), "绝对顶部": d(t_abs_peak), "顶部确认日": d(confirm_pos), "退潮底部": d(tb),
                "谷底→顶部超额": gain, "顶部→底部相对跌幅": rs_ret(tp, tb),
                "顶部→底部绝对跌幅": close[tb, j] / close[tp, j] - 1,
                "_t0": t0, "_start": t_start, "_accel": t_accel, "_crowd": t_crowd, "_top": tp,
                "_bottom": tb, "_confirm": confirm_pos, "_peak_ok": peak_confirmed, "_bottom_ok": bottom_confirmed,
                "首次超额→顶部剩余超额": rs_ret(t_start, tp), "拥挤→顶部剩余超额": rs_ret(t_crowd, tp),
                "首次超额→底部超额": rs_ret(t_start, tb) if bottom_confirmed else np.nan,
                "拥挤→底部超额": rs_ret(t_crowd, tb) if bottom_confirmed else np.nan,
            })
    ep = pd.DataFrame(rows)
    if ep.empty:
        return ep
    ep = ep[ep["相对顶部"] >= P.study_start].sort_values("谷底").reset_index(drop=True)
    return ep


def _span(ep: pd.DataFrame, a: str, b: str, need_peak: bool = True, need_bottom: bool = False) -> pd.Series:
    m = ep[a].notna() & ep[b].notna()
    if need_peak:
        m &= ep["_peak_ok"]
    if need_bottom:
        m &= ep["_bottom_ok"]
    return (ep.loc[m, b] - ep.loc[m, a]).astype(float)


def run(P: Panels) -> StudyResult:
    c = P.cfg["lifecycle"]
    res = StudyResult(
        "A", "主线生命周期",
        "主线从第一次超额收益出现，到加速、拥挤、顶部、退潮到底分别多长时间？时间规律是否稳定到可以用来判断阶段？",
        meta=P.meta(),
    )
    res.definitions = [
        f"主线：行业/中证全指的相对强弱线 zigzag({c['rs_swing']:.0%}) 上涨段，谷→峰超额 ≥ {c['min_excess']:.0%}，"
        f"≥ {c['min_days']} 个交易日，且期间 60 日超额排名曾进入前 {c['top_rank']}",
        f"首次超额：谷底之后 20 日超额收益首次 ≥ {c['start_excess_20d']:.0%}（t 日可观测）",
        f"加速：20 日超额收益首次 ≥ {c['accel_excess_20d']:.0%}（t 日可观测）",
        f"拥挤：行业成交额占全A比重处于自身过去 {P.cfg['common']['pct_window']} 日的 {c['crowd_pct']:.0%} 分位以上（t 日可观测）",
        "相对顶部 / 退潮底部：相对强弱线的 zigzag 峰/谷（事后才能确认，只作为结果）",
        f"顶部确认日：相对强弱线从顶部回撤满 {c['rs_swing']:.0%} 的那天——现实中最早能“确认见顶”的时间",
        "时长单位均为交易日；只统计已完成的阶段（右截断样本不进分布）",
    ]
    ep = detect_episodes(P)
    if ep.empty:
        res.findings.append("按当前定义没有识别出任何主线波段（检查数据区间或放宽 min_excess）。")
        return res

    pos = {k: ep[f"_{k}"].astype(float) for k in ("t0", "start", "accel", "crowd", "top", "bottom", "confirm")}
    pos_df = pd.DataFrame(pos)
    pos_df["_peak_ok"] = ep["_peak_ok"]
    pos_df["_bottom_ok"] = ep["_bottom_ok"]
    spans = {
        "谷底→首次超额": _span(pos_df, "t0", "start"),
        "首次超额→加速": _span(pos_df, "start", "accel"),
        "加速→相对顶部": _span(pos_df, "accel", "top"),
        "首次超额→拥挤": _span(pos_df, "start", "crowd", need_peak=False),
        "拥挤→相对顶部(负=顶部后才拥挤)": _span(pos_df, "crowd", "top"),
        "首次超额→相对顶部": _span(pos_df, "start", "top"),
        "谷底→相对顶部": _span(pos_df, "t0", "top"),
        "相对顶部→顶部确认": _span(pos_df, "top", "confirm"),
        "相对顶部→退潮底部": _span(pos_df, "top", "bottom", need_bottom=True),
    }
    rows = []
    for name, s in spans.items():
        dsc = stats.describe(s)
        iqr = dsc["p75"] - dsc["p25"]
        rows.append({"阶段": name, "样本": dsc["n"], "均值(日)": dsc["mean"], "中位(日)": dsc["median"],
                     "P25(日)": dsc["p25"], "P75(日)": dsc["p75"], "最短(日)": dsc["min"], "最长(日)": dsc["max"],
                     "离散度IQR/中位": iqr / dsc["median"] if dsc["median"] else np.nan})
    dur = pd.DataFrame(rows)

    # 退潮/上涨时长比
    done = ep["_peak_ok"] & ep["_bottom_ok"]
    ratio = ((ep.loc[done, "_bottom"] - ep.loc[done, "_top"]) / (ep.loc[done, "_top"] - ep.loc[done, "_t0"])).astype(float)

    # 信号出现后的剩余空间
    rs_arr = P.rs
    rem_rows = []
    for stage, key in zip(STAGES, ("start", "accel", "crowd")):
        m = ep[f"_{key}"].notna() & ep["_peak_ok"]
        sub = ep[m]
        if sub.empty:
            rem_rows.append({"信号": stage, "样本": 0})
            continue
        days_to_top = (sub["_top"] - sub[f"_{key}"]).astype(float)
        rem = np.array([rs_arr[c_].iloc[int(tp)] / rs_arr[c_].iloc[int(t)] - 1
                        for c_, t, tp in zip(sub["代码"], sub[f"_{key}"], sub["_top"])])
        mb = sub["_bottom_ok"]
        to_bottom = np.array([rs_arr[c_].iloc[int(tb)] / rs_arr[c_].iloc[int(t)] - 1
                              for c_, t, tb in zip(sub.loc[mb, "代码"], sub.loc[mb, f"_{key}"], sub.loc[mb, "_bottom"])])
        lo, hi = stats.bootstrap_ci(rem, stat=np.median, rng=P.rng)
        rem_rows.append({
            "信号": stage, "样本": len(sub),
            "信号在顶部之后的比例": float(np.mean(days_to_top < 0)),
            "距顶部天数中位(日)": float(np.median(days_to_top)),
            "剩余超额中位": float(np.median(rem)), "剩余超额90%CI低": lo, "剩余超额90%CI高": hi,
            "剩余超额P25": float(np.quantile(rem, 0.25)),
            "持有到退潮底部超额中位": float(np.median(to_bottom)) if len(to_bottom) else np.nan,
            "持有到底部为负的比例": float(np.mean(to_bottom < 0)) if len(to_bottom) else np.nan,
        })
    remain = pd.DataFrame(rem_rows)

    # 拥挤 vs 顶部
    peak_ok = ep[ep["_peak_ok"]]
    n_ok = len(peak_ok)
    before = int(((peak_ok["_crowd"].notna()) & (peak_ok["_crowd"] <= peak_ok["_top"])).sum())
    after = int(((peak_ok["_crowd"].notna()) & (peak_ok["_crowd"] > peak_ok["_top"])).sum())
    never = int(peak_ok["_crowd"].isna().sum())
    crowd_tbl = pd.DataFrame([
        {"情形": "拥挤出现在相对顶部之前（含当天）", "次数": before, "比例": before / n_ok if n_ok else np.nan},
        {"情形": "拥挤出现在相对顶部之后", "次数": after, "比例": after / n_ok if n_ok else np.nan},
        {"情形": "整个波段未达拥挤阈值", "次数": never, "比例": never / n_ok if n_ok else np.nan},
    ])

    # 前后两段稳定性
    split_rows = []
    for label, m in (("前段", ep["谷底"] <= P.split), ("后段", ep["谷底"] > P.split)):
        sub = pos_df[m.to_numpy()]
        for name in ("首次超额→相对顶部", "相对顶部→退潮底部"):
            a, b = ("start", "top") if name.startswith("首次") else ("top", "bottom")
            s = _span(sub, a, b, need_bottom=(b == "bottom"))
            dsc = stats.describe(s)
            split_rows.append({"时期": label, "阶段": name, "样本": dsc["n"], "中位(日)": dsc["median"],
                               "P25(日)": dsc["p25"], "P75(日)": dsc["p75"]})
    split_tbl = pd.DataFrame(split_rows)

    # ---- 表格 ----
    show_cols = ["行业", "状态", "左截断", "谷底", "首次超额", "加速", "拥挤", "相对顶部", "顶部确认日", "退潮底部",
                 "谷底→顶部超额", "顶部→底部相对跌幅", "首次超额→顶部剩余超额", "拥挤→顶部剩余超额"]
    res.add("阶段时长分布（交易日）", dur, "离散度 = 四分位距/中位数；> 1 表示同一阶段在不同主线之间长短差异极大。",
            pct_cols=[])
    res.add("看到信号后还剩多少空间（相对强弱）", remain,
            "“剩余超额”= 从信号日到相对顶部的超额；“持有到退潮底部”= 一直拿到退潮结束的超额（衡量不卖的代价）。")
    res.add("拥挤信号与顶部的先后", crowd_tbl, "只统计顶部已确认的波段。", pct_cols=["比例"])
    res.add("前后两段对比", split_tbl, "如果两段的中位数差异很大，说明“生命周期长度”本身随市场结构变化，不能直接外推。",
            pct_cols=[])
    res.add("主线波段明细", ep[show_cols], "左截断=数据起点附近开始的波段，真实起点可能更早。")
    ongoing = ep[ep["状态"] != "完成"]
    if not ongoing.empty:
        res.add("进行中的主线（右截断，不计入分布）", ongoing[["行业", "状态", "谷底", "首次超额", "加速", "拥挤", "相对顶部", "谷底→顶部超额"]])

    # ---- 结论 ----
    n_all = len(ep)
    res.findings.append(
        f"共识别 {n_all} 轮主线（涉及 {ep['代码'].nunique()} 个行业），其中已完成 {int(done.sum())} 轮、进行中 {n_all - int(done.sum())} 轮。"
    )
    d = dur.set_index("阶段")
    for name in ("首次超额→相对顶部", "相对顶部→退潮底部", "相对顶部→顶部确认"):
        r = d.loc[name]
        if r["样本"] == 0:
            continue
        disp = r["离散度IQR/中位"]
        verdict = "离散度大，**不能用固定天数判断主线阶段**" if np.isfinite(disp) and disp > 1 else (
            "长度相对集中，可作为粗略参考" if np.isfinite(disp) and disp < 0.5 else "离散度中等，只能作为粗略参考")
        res.findings.append(
            f"{name}：中位 {num(r['中位(日)'])} 个交易日（P25–P75：{num(r['P25(日)'])}–{num(r['P75(日)'])}，n={int(r['样本'])}），{verdict}。"
        )
    if len(ratio):
        res.findings.append(f"退潮时长/上涨时长 的中位比为 {ratio.median():.2f}（n={len(ratio)}）——"
                            + ("退潮通常比上涨快。" if ratio.median() < 1 else "退潮并不比上涨快。"))
    if n_ok:
        lo, hi = stats.wilson_ci(before, n_ok)
        res.findings.append(
            f"拥挤信号在相对顶部之前出现的比例为 {before}/{n_ok}（90%CI {pct(lo, 0)}–{pct(hi, 0)}），"
            f"顶部之后才拥挤 {after} 次，全程未拥挤 {never} 次。"
        )
    rr = remain.set_index("信号")
    if "拥挤" in rr.index and rr.loc["拥挤", "样本"] > 0:
        r = rr.loc["拥挤"]
        res.findings.append(
            f"出现拥挤信号后：距相对顶部中位 {num(r['距顶部天数中位(日)'])} 日，剩余超额中位 {pct(r['剩余超额中位'])}"
            f"（90%CI {pct(r['剩余超额90%CI低'])}~{pct(r['剩余超额90%CI高'])}）；若拿到退潮底部，超额中位 {pct(r['持有到退潮底部超额中位'])}，"
            f"为负的比例 {pct(r['持有到底部为负的比例'], 0)}。"
        )
    if "相对顶部→顶部确认" in d.index and d.loc["相对顶部→顶部确认", "样本"] > 0:
        res.findings.append(
            f"“确认见顶”天然滞后：相对强弱从顶部回撤 {c['rs_swing']:.0%} 才能确认，中位滞后 "
            f"{num(d.loc['相对顶部→顶部确认', '中位(日)'])} 日——事后画出的“顶部”在当时不可见。"
        )
    res.caveats = [
        "顶部/底部由事后 zigzag 确定，只能作为研究对象，不能当作 t 日可用信号。",
        "申万一级行业粒度较粗：真实主线常常是二级/三级行业或概念（如 CPO、算力），一级行业会稀释信号。可把 sector_daily 换成二级行业重跑。",
        "2015—2026 的一级行业主线约二三十轮，统计量置信区间很宽；时长分布只描述历史，不保证未来。",
        "拥挤度用成交占比的自身历史分位，行业规模变化（如电子行业扩容）会让早年分位偏低。",
    ]
    return res
