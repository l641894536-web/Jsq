"""Markdown 报告（中文）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ashare_lab.report import df_to_markdown

CAT_CN = {"trend": "趋势", "momentum": "动量", "oscillator": "摆动", "channel": "通道", "volatility": "波动",
          "volume": "量能", "ashare": "A股特有", "events": "事件"}


def md_doc(title: str, intro: list[str], sections: list[tuple]) -> str:
    """sections: (标题, DataFrame 或 文本, 说明, 百分比列)。"""
    lines = [f"# {title}", ""]
    lines += intro + [""]
    for sec in sections:
        head, body = sec[0], sec[1]
        note = sec[2] if len(sec) > 2 else ""
        pcts = sec[3] if len(sec) > 3 else []
        lines += [f"## {head}", ""]
        if note:
            lines += [note, ""]
        if isinstance(body, pd.DataFrame):
            lines += [df_to_markdown(body, pct_cols=pcts, max_rows=300), ""]
        elif body:
            lines += [str(body), ""]
    lines.append(f"_生成时间：{datetime.now():%Y-%m-%d %H:%M}_")
    return "\n".join(lines)


def save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fmt_sig(v: pd.DataFrame) -> pd.DataFrame:
    return v.assign(类别=v["category"].map(CAT_CN))


def predictive_table(v: pd.DataFrame, h: int) -> pd.DataFrame:
    d = v[v.h == h].copy()
    d = d.reindex(d["stat_t"].abs().sort_values(ascending=False).index)
    return pd.DataFrame({
        "信号": d["signal"], "类别": d["category"].map(CAT_CN),
        "发现集 IC": d["disc_ic_mean"], "发现集 t值": d["disc_stat_t"],
        "验证集 IC": d["ic_mean"], "验证集 事件超额": np.where(d["event"], d["stat_mean"], np.nan),
        "验证集 t值": d["stat_t"], "q值": d["q"], "RC p值": d["rc_p"],
        "同向": d["same_sign"], "显著": d["sig"],
    })


def trade_table(v: pd.DataFrame, only_sig: bool = True) -> pd.DataFrame:
    d = v[v["sig"]] if only_sig else v
    d = d.sort_values(["h", "ann_net"], ascending=[True, False])
    return pd.DataFrame({
        "信号": d["signal"], "持有期(日)": d["h"], "方向": np.where(d["direction"] > 0, "做多高值", "做多低值"),
        "验证集 t值": d["stat_t"], "FM t值": d["fm_t"],
        "年化超额(毛)": d["ann_gross"], "年化超额(净0.3%)": d["ann_net"], "90%CI下限": d["ci_lo"], "90%CI上限": d["ci_hi"],
        "年化超额(净0.5%)": d["ann_stress"], "换手/期": d["turnover"], "买入受阻比例": d["blocked"],
        "卖出顺延比例": d["delayed"], "平均持股数": d["n_hold"], "仅回避用": d["avoid_only"],
    })


TRADE_PCT = ["年化超额(毛)", "年化超额(净0.3%)", "90%CI下限", "90%CI上限", "年化超额(净0.5%)", "换手/期", "买入受阻比例", "卖出顺延比例"]


def grade_table(v: pd.DataFrame) -> pd.DataFrame:
    d = v[v["sig"]].sort_values(["pre_grade", "h", "stat_t"], key=lambda s: s.abs() if s.name == "stat_t" else s,
                                ascending=[True, True, False])
    plat = d["plateau"].map({1.0: "成立", 0.0: "不成立"}).fillna("无参数族")
    return pd.DataFrame({
        "信号": d["signal"], "持有期(日)": d["h"], "验证集 t值": d["stat_t"], "q值": d["q"],
        "增量信息(FM)": d["fm_ok"], "可交易(净超额CI>0)": d["bt_ok"], "参数平台": plat,
        "基础因子": d["base_factor"], "仅回避用": d["avoid_only"], "测试前等级": d["pre_grade"],
    })


def calibration_doc(rows: list[dict], planted: dict | None, meta: list[str]) -> str:
    df = pd.DataFrame(rows)
    secs = [("零假设：什么规律都没有的模拟数据", df,
             "每个随机种子 = 一套独立的模拟A股（1000只股票、2010—2022），74 个信号 × 3 个持有期 = 222 项检验。"
             "“显著”= 验证集 |t|>3、BH q<0.05、且与发现集同向（与真实数据完全相同的门槛）。", [])]
    if planted:
        secs.append(("检验力：埋入已知的短期反转信号", planted["table"], planted["note"], planted.get("pct", [])))
    return md_doc("指标实验室｜第0步 误报率与检验力校准", meta, secs)


def _meta_lines(meta: dict) -> list[str]:
    return [f"- {k}：{v}" for k, v in meta.items()]


def write_dv(out: Path, summ: pd.DataFrame, res: dict, cfg: dict, meta: dict) -> None:
    v = res["verdict"]
    hs = cfg["trade"]["horizons"]
    intro = ["> 预注册协议：docs/indicators_protocol.md；参数：config/indicators.toml。**本文件在打开最终测试集之前生成。**", ""]
    intro += _meta_lines(meta)
    # 01 预测力
    secs = []
    for h in hs:
        secs.append((f"持有期 {h} 日（按验证集 |t| 排序）", predictive_table(v, h),
                     "IC = 每日横截面 Rank IC 的均值；事件类的 t 值与 q 值基于“事件超额”（事件股 − 股票池）。"
                     "显著 = 验证集 |t|>3、BH q<0.05、与发现集同向。RC p值 = 222 项一起做最大 t 自助法后的族错误率校正 p 值。",
                     ["验证集 事件超额"]))
    n_sig = v.groupby("h")["sig"].sum().to_dict()
    head = [f"- 显著的 信号×持有期：" + "，".join(f"{h}日 {int(n_sig.get(h, 0))} 个" for h in hs) + f"（共 {int(v['sig'].sum())}/{len(v)}）"]
    save(out / "01_预测力_发现集与验证集.md", md_doc("指标实验室｜第1~2步 预测力与多重检验", intro + head, secs))
    # 02 增量信息与可交易性
    tt = trade_table(v)
    secs = [("显著信号的增量信息与可交易性（验证集）", tt,
             "FM t值：控制 ret_1、ret_20、mom_12_1、vol_20、log_amount_20、市值分层、申万一级行业后的信号系数 t 值（|t|>2 且同向 = 有增量信息）。"
             "年化超额：前 10%（或事件股）等权、t+1 开盘买入、持有 h 日，相对可入选股票等权；90%CI 为扣 0.3% 成本后的块自助法区间。",
             TRADE_PCT)]
    save(out / "02_增量信息与可交易性.md", md_doc("指标实验室｜第3~4步 增量信息与可交易性", intro, secs))
    # 03 稳健性
    secs = []
    fam_rows = []
    for fam, names in cfg["families"].items():
        for h in hs:
            r = {"参数族": fam, "持有期(日)": h}
            for nm in names:
                x = v[(v.signal == nm) & (v.h == h)]
                r[nm] = float(x["stat_t"].iloc[0]) if len(x) else np.nan
            fam_rows.append(r)
    fam_df = pd.DataFrame(fam_rows)
    fam_txt = []
    for fam, names in cfg["families"].items():
        sub = fam_df[fam_df["参数族"] == fam][["持有期(日)"] + names]
        fam_txt.append(f"**{fam}**（验证集 t 值）\n\n" + df_to_markdown(sub, pct_cols=[]))
    secs.append(("参数平台：同一参数族各参数的验证集 t 值", "\n\n".join(fam_txt),
                 "平台成立 = 相邻参数同号且 |t| ≥ 该参数 |t| 的 50%（逐个参数的判定见 04 与 csv）。"))
    sig = v[v["sig"]]
    val = summ[summ.split == "validation"].set_index(["signal", "h"])
    if len(sig):
        idx = list(zip(sig.signal, sig.h))
        tier = val.loc[idx, ["ic_t300_mean", "ic_t300_tstat", "ic_t500_mean", "ic_t500_tstat", "ic_t1000_mean",
                             "ic_t1000_tstat", "ic_tsmall_mean", "ic_tsmall_tstat"]].reset_index()
        tier.columns = ["信号", "持有期(日)", "沪深300 IC", "沪深300 t值", "中证500 IC", "中证500 t值",
                        "中证1000 IC", "中证1000 t值", "其余小票 IC", "其余小票 t值"]
        secs.append(("按市值分层的 IC（验证集，显著信号）", tier, "用全池秩在层内求相关（描述性，不参与判定）。", []))
        reg = res["regime"].merge(sig[["signal", "h"]], on=["signal", "h"])
        reg = reg.rename(columns={"signal": "信号", "h": "持有期(日)"})
        rd = res.get("regime_days", {})
        secs.append(("按市场环境的主统计量（验证集，显著信号）", reg,
                     "中证800 均线法（年线 + 20 日斜率，连续 10 天确认）。验证集天数：" +
                     "，".join(f"{k} {v_} 天" for k, v_ in rd.items() if isinstance(k, str)) + "。事件类为事件超额，其余为 IC。",
                     []))
        dec = val.loc[idx, [f"d{g}" for g in range(1, 11)] + ["mono"]].reset_index()
        dec = dec[~dec["signal"].str.startswith("ev_")]
        dec.columns = ["信号", "持有期(日)"] + [f"第{g}组收益" for g in range(1, 11)] + ["单调性(秩相关)"]
        secs.append(("十分组平均收益（验证集，显著的连续信号；第1组=信号最低）", dec,
                     "每组为 t+1 开盘到 t+1+h 开盘的平均收益（未扣成本、未减基准）。", [f"第{g}组收益" for g in range(1, 11)]))
    pl = summ[summ.split == "validation"]["placebo_t"].abs()
    secs.append(("安慰剂检验", f"把信号按固定随机置换错配到其他股票后重算 IC：222 项中 |t|>3 的有 {int((pl > 3).sum())} 项，"
                 f"|t|>2 的有 {int((pl > 2).sum())} 项（纯随机时约 0 项与 11 项）。", ""))
    save(out / "03_稳健性.md", md_doc("指标实验室｜第5步 稳健性", intro, secs))
    # 04 测试前判定
    g = grade_table(v)
    cnt = v[v["sig"]].groupby("pre_grade").size().to_dict()
    lines = [f"- 显著的 信号×持有期 {int(v['sig'].sum())} 个，其中 A候选 {cnt.get('A候选', 0)} 个、B {cnt.get('B', 0)} 个；"
             f"其余 {int((~v['sig']).sum())} 个为 C（无效）。",
             "- A候选 还需在最终测试集上满足：IC 同号且 |t|>2、扣 0.3% 成本后超额 > 0，才定为 A。"]
    save(out / "04_测试前判定.md", md_doc("指标实验室｜测试前判定（打开测试集之前提交）", intro + lines,
                                       [("显著信号的逐项判定", g, "", [])]))


def final_grades(v: pd.DataFrame, test: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    t = test[test.split == "test"].set_index(["signal", "h"])
    f = v.set_index(["signal", "h"]).copy()
    for c, src in (("test_ic", "ic_mean"), ("test_t", "stat_t"), ("test_ann_net", "ann_net"), ("test_ci_lo", "ci_lo"),
                   ("test_ann_gross", "ann_gross"), ("test_turnover", "turnover")):
        f[c] = t[src]
    f["test_ok"] = (np.sign(f["test_t"]) == np.sign(f["stat_t"])) & (f["test_t"].abs() > 2) & (f["test_ann_net"] > 0)
    f["test_ic_ok"] = (np.sign(f["test_t"]) == np.sign(f["stat_t"])) & (f["test_t"].abs() > 2)
    f["final_grade"] = np.where(~f["sig"], "C", np.where((f["pre_grade"] == "A候选") & f["test_ok"], "A", "B"))
    return f.reset_index()


def write_test(out: Path, f: pd.DataFrame, meta: dict) -> None:
    intro = _meta_lines(meta)
    s = f[f["sig"]].copy()
    s = s.sort_values(["final_grade", "h", "test_t"], key=lambda x: x.abs() if x.name == "test_t" else x,
                      ascending=[True, True, False])
    tbl = pd.DataFrame({
        "信号": s["signal"], "持有期(日)": s["h"], "方向": np.where(s["direction"] > 0, "做多高值", "做多低值"),
        "验证集 t值": s["stat_t"], "测试集 IC": s["test_ic"], "测试集 t值": s["test_t"],
        "测试集年化超额(毛)": s["test_ann_gross"], "测试集年化超额(净0.3%)": s["test_ann_net"], "测试集90%CI下限": s["test_ci_lo"],
        "测试前等级": s["pre_grade"], "最终等级": s["final_grade"],
    })
    pct = ["测试集年化超额(毛)", "测试集年化超额(净0.3%)", "测试集90%CI下限"]
    nsig = f[~f["sig"]]
    rev = nsig[(nsig["test_t"].abs() > 3)]
    rev_tbl = pd.DataFrame({"信号": rev["signal"], "持有期(日)": rev["h"], "验证集 t值": rev["stat_t"],
                            "测试集 t值": rev["test_t"]})
    secs = [("验证集显著信号在最终测试集上的表现", tbl, "测试集：2023-01 ~ 2026-09，只打开一次。方向沿用发现集。", pct),
            ("参考：验证集不显著、但测试集 |t|>3 的（不改变判定，只作记录）", rev_tbl, "", [])]
    save(out / "05_最终测试集.md", md_doc("指标实验室｜第6步 最终测试集", intro, secs))


def write_timing(out: Path, res: dict, cfg: dict, synthetic: bool = False) -> None:
    t = res["tests"].copy()
    tim = res["timing"]
    sc = cfg["secondary"]
    intro = ["> 次要研究（协议第 6 节），**只作参考，不参与主研究判定**。" + ("**零假设模拟数据**，用于检查误报率。" if synthetic else ""),
             f"- 方向：{sc['direction_period'][0]} ~ {sc['direction_period'][1]} 的平均时间序列 IC 符号；评估：{sc['eval_period'][0]} ~ 2026-09。",
             f"- 标的：宽基 {len(res['groups']['宽基'])} 个（{'、'.join(res['groups']['宽基'])}），行业 {len(res['groups']['行业'])} 个（申万一级等权合成）。",
             f"- 显著 = BH q<0.05（共 {len(t)} 项）且与定方向期同号；p 值取“同一平移量的循环平移检验”与“按 N/h 个独立样本的 t 检验”中较大者。"]
    cnt = t.groupby(["group", "h"])["sig"].agg(["sum", "count"]).reset_index()
    cnt.columns = ["组", "持有期(日)", "显著个数", "检验数"]
    secs = [("显著个数", cnt, "", [])]
    sig = t[t["sig"]].copy()
    if len(tim):
        agg = tim.groupby(["signal", "h", "group"]).agg(
            择时夏普=("择时夏普", "mean"), 持有夏普=("持有夏普", "mean"), 择时年化=("择时年化", "mean"), 持有年化=("持有年化", "mean"),
            择时最大回撤=("择时最大回撤", "mean"), 持有最大回撤=("持有最大回撤", "mean"), 平均仓位=("平均仓位", "mean"), 年换手=("年换手", "mean"),
            夏普更高占比=("择时夏普", lambda x: np.nan)).reset_index()
        win = tim.assign(w=tim["择时夏普"] > tim["持有夏普"]).groupby(["signal", "h", "group"])["w"].mean().reset_index()
        agg["夏普更高占比"] = win["w"].to_numpy()
        t = t.merge(agg, on=["signal", "h", "group"], how="left")
        sig = t[t["sig"]].copy()
    def tbl(d):
        d = d.reindex(d["ic"].abs().sort_values(ascending=False).index)
        cols = {"signal": "指标", "group": "组", "h": "持有期(日)", "dir_ic": "定方向期 IC", "ic": "评估期 IC", "same_sign_frac": "同号标的占比",
                "p": "p值", "q": "q值"}
        extra = [c for c in ("择时夏普", "持有夏普", "夏普更高占比", "择时年化", "持有年化", "择时最大回撤", "持有最大回撤", "平均仓位", "年换手") if c in d]
        return d[list(cols) + extra].rename(columns=cols)
    pct = ["同号标的占比", "夏普更高占比", "择时年化", "持有年化", "择时最大回撤", "持有最大回撤", "平均仓位"]
    secs.append(("显著的 指标×持有期×组", tbl(sig) if len(sig) else "（无）",
                 "IC 为组内各标的时间序列 IC 的平均；择时指标为组内各标的的平均（评估期）。", pct))
    for g in ("宽基", "行业"):
        d = t[t.group == g]
        if len(d):
            secs.append((f"{g}：|IC| 最大的 20 项（不论是否显著）", tbl(d).head(20), "", pct))
    title = "指标实验室｜次要研究：指数与行业择时" + ("（零假设模拟）" if synthetic else "")
    save(out / ("06_次要研究_指数与行业择时.md" if not synthetic else "零假设自检.md"), md_doc(title, intro, secs))


def write_pruning(out: Path, res: dict, title_suffix: str = "") -> None:
    intro = ["> 协议：docs/indicators_pruning.md（先于计算提交）。逐步选择只用发现集（2012—2017）；验证集（2018—2022）确认与排除；"
             "测试集（2023—2026）在主研究中已按单个指标打开过，这里只作一致性检查。"]
    secs = []
    fam = res["families"].copy()
    fam["类别"] = ""
    groups = fam.groupby("家族")["指标"].apply(lambda x: "、".join(x)).reset_index()
    groups["个数"] = groups["指标"].str.count("、") + 1
    groups = groups.sort_values("个数", ascending=False)
    secs.append(("指标家族（发现集平均横截面相关 |ρ| ≥ 0.7 聚为一类）", groups[["个数", "指标"]],
                 f"74 个指标聚成 {len(groups)} 个家族。", []))
    for h, per in res["horizons"].items():
        secs.append((f"持有期 {h} 日：逐步选择过程（发现集）", per["steps"], "每步加入“控制已选因子后增量 t 值”最大的指标；最大 |t| ≤ 3 时停止。", []))
        if len(per["table"]):
            secs.append((f"持有期 {h} 日：入选因子的联合回归", per["table"],
                         "系数单位：标签秩分位 / 指标秩分位。确认 = 验证集 |t|>2 且与发现集同号。", []))
        ex = per["excluded"]
        if "判定" in ex:
            cnt = ex["判定"].value_counts().to_dict()
            keep = ex[ex["判定"].isin(["仍有独立信息", "边缘"])]
            secs.append((f"持有期 {h} 日：未入选指标（验证集，控制全部入选因子后）",
                         "；".join(f"{k} {v} 个" for k, v in cnt.items()) + "。" +
                         ("\n\n仍有独立信息 / 边缘的：\n\n" + df_to_markdown(keep, pct_cols=[]) if len(keep) else ""), ""))
        if "composite" in per:
            secs.append((f"持有期 {h} 日：合成分数做多前 10%", per["composite"],
                         "合成分数 = Σ 发现集联合回归系数 × 指标秩分位；口径与主研究相同（t+1 开盘买、涨跌停处理、相对股票池等权）。",
                         ["年化超额(毛)", "年化超额(净0.3%)", "90%CI下限", "90%CI上限", "年化超额(净0.5%)", "换手/期"]))
    save(out / f"第二轮_因子去冗余{title_suffix}.md", md_doc(f"指标实验室｜第二轮：因子去冗余{title_suffix}", intro, secs))
