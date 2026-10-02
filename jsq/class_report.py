"""按资产类别的研究报告（classlab 的输出 -> 单文件 HTML）。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .classlab import CLASS_EXITS, DECAY_H, EXIT_CN
from .regime import FILTER_CN, REGIMES
from .report import CSS, JS, _bg, _e, _spark, _table, _tabs, num, pct

GROUP_ORDER = ["加密", "美股/ETF", "贵金属", "能源"]
GROUP_NOTE = {
    "加密": "BTC、ETH，2023-01 起约 3.7 年数据。资金费率、持仓量、多空比、ETH/BTC 强弱、趋势、新闻冲击。",
    "美股/ETF": "21 个美股合约，2026 年陆续上线，每个只有 2~7 个月。开盘跳空、开盘区间突破、休市涨跌、QQQ 联动。",
    "贵金属": "黄金 XAU/PAXG/XAUT、白银、铂、钯。趋势、亚洲盘区间突破、金银相对强弱、盘口深度、新闻冲击。",
    "能源": "WTI、布伦特、天然气，2026-04 起约 5 个月。趋势、EIA 库存数据反应、新闻冲击（讲话、OPEC 等）。",
}


def _cfg_text(s: str) -> str:
    if not isinstance(s, str) or "|" not in s:
        return ""
    e, f = s.split("|", 1)
    return f"{EXIT_CN.get(e, e)} · {FILTER_CN.get(f, f)}"


def build_class_report(run_dir: Path, fee: float = 0.0005, slippage: float = 0.0002, fragment: bool = False) -> Path:
    run_dir = Path(run_dir)
    oos = pd.read_csv(run_dir / "class_oos.csv")
    reg = pd.read_csv(run_dir / "class_regime.csv")
    dec = pd.read_csv(run_dir / "class_decay.csv")
    best = json.loads((run_dir / "class_best.json").read_text())
    cv_p = run_dir / "class_curves.csv.gz"
    curves = pd.read_csv(cv_p, parse_dates=["time"]) if cv_p.exists() else pd.DataFrame()
    cost_bps = (fee + slippage) * 2 * 1e4
    groups = [g for g in GROUP_ORDER if g in set(oos["group"])]

    parts = [f"<h1>分资产类别 策略研究</h1><div class=\"mut\">手续费 {pct(fee, 3)}/边 · 滑点 {pct(slippage, 3)}/边"
             f"（一来一回约 {num(cost_bps, 0)} 基点）· 同类标的合并检验 · 3 段滚动样本外 · 所有数字为扣费后样本外结果</div>"]

    # ---------- 摘要
    items = []
    for g in groups:
        o = oos[(oos["group"] == g) & (oos["strategy"] != "AUTO") & (oos["trades"] >= 30)]
        good = o[(o["exp_bps"] > 0) & (o["t_R"] > 1.5) & (o["sym_pos"] >= 0.5)].sort_values("t_R", ascending=False)
        meta = best.get(g, {}).get("_meta", {})
        head = f"<b>{_e(g)}</b>（样本外 {_e(meta.get('oos_start', ''))} ~ {_e(meta.get('end', ''))}）："
        if len(good):
            li = "；".join(
                f"{_e(r.label)}（{_e(_cfg_text(r.exit_filter))}）每笔 {num(r.exp_bps, 1)} 基点，"
                f"胜率 {pct(r.win_rate, 0)}，盈亏比 {num(r.payoff, 2)}，{int(r.trades)} 笔，t={num(r.t_R, 1)}"
                for r in good.head(3).itertuples())
            items.append(f"<li>{head}{li}</li>")
        else:
            pos = o[o["exp_bps"] > 0].sort_values("exp_bps", ascending=False)
            hint = (f"期望为正但不显著的：{'、'.join(_e(x) for x in pos['label'].head(3))}" if len(pos)
                    else "所有策略样本外期望都为负")
            items.append(f"<li>{head}没有显著为正（t&gt;1.5 且过半标的盈利）的策略。{hint}。</li>")
        a = oos[(oos["group"] == g) & (oos["strategy"] == "AUTO")]
        if len(a):
            a = a.iloc[0]
            items[-1] = items[-1][:-5] + (f" 每段自动挑训练期最好的策略：每笔 {num(a.exp_bps, 1)} 基点，"
                                         f"{int(a.trades)} 笔。</li>")
    parts.append('<h2>结论摘要</h2><div class="card"><ul>' + "".join(items) + "</ul>"
                 '<p class="mut">判定标准：样本外 ≥30 笔、按 R 倍数的 t&gt;1.5、过半标的盈利。胜率低不要紧，'
                 '盈亏比 × 胜率决定期望。</p></div>')

    # ---------- 每类一个标签页
    panes = {}
    cmap = {}
    if len(curves):
        for (g, s), x in curves.groupby(["group", "strategy"]):
            cmap[(g, s)] = pd.Series(1 + x["cum_bps"].to_numpy() / 1e4, index=x["time"])
    for g in groups:
        o = oos[oos["group"] == g].sort_values("exp_R", ascending=False)
        rows = []
        for r in o.itertuples():
            if not r.trades:
                continue
            rows.append([
                f'<td class="l">{_e(r.label)} <span class="mut">{_e(r.strategy)}</span></td>',
                f'<td class="l">{_e(_cfg_text(r.exit_filter))}</td>',
                f"<td>{int(r.trades)}</td>", f"<td>{int(r.symbols)}</td>",
                f"<td>{pct(r.win_rate, 0)}</td>", f"<td>{num(r.avg_win_bps, 0)}</td>", f"<td>{num(r.avg_loss_bps, 0)}</td>",
                f"<td>{num(r.payoff, 2)}</td>",
                f"<td{_bg(r.exp_bps, 40)}><b>{num(r.exp_bps, 1)}</b></td>", f"<td{_bg(r.exp_R, 0.3)}>{num(r.exp_R, 2)}</td>",
                f"<td>{num(r.profit_factor, 2)}</td>", f"<td{_bg(r.t_R, 3)}>{num(r.t_R, 1)}</td>",
                f"<td>{num(r.avg_hold_h, 0)}</td>", f"<td>{pct(r.sym_pos, 0)}</td>",
                f"<td>{_spark(cmap.get((g, r.strategy)), None)}</td>"])
        tbl = _table(["策略", "常选出场 · 行情过滤", "笔数", "标的", "胜率", "平均盈利", "平均亏损", "盈亏比",
                      "每笔期望(基点)", "期望(R)", "PF", "t(R)", "持仓h", "盈利标的", "样本外累计"], rows, left_cols=2)

        # 行情状态
        rg = reg[reg["group"] == g]
        rrows = []
        for r in o.itertuples():
            if r.strategy == "AUTO":
                continue
            row = [f'<td class="l">{_e(r.label)}</td>']
            for rgm in REGIMES:
                x = rg[(rg["strategy"] == r.strategy) & (rg["regime"] == rgm)]
                if not len(x) or x.iloc[0]["trades"] < 5:
                    row.append("<td>–</td>")
                    continue
                x = x.iloc[0]
                row.append(f'<td{_bg(x.exp_bps, 40)} title="胜率 {pct(x.win_rate, 0)} 盈亏比 {num(x.payoff, 2)}">'
                           f'{num(x.exp_bps, 1)} <span class="mut">({int(x.trades)})</span></td>')
            rrows.append(row)
        rtbl = _table(["策略 \\ 行情"] + REGIMES, rrows)

        # 持仓时间曲线
        d = dec[dec["group"] == g]
        drows = []
        for r in o.itertuples():
            if r.strategy == "AUTO":
                continue
            x = d[d["strategy"] == r.strategy].set_index("horizon_h")
            if not len(x):
                continue
            peak = x["exp_bps"].idxmax()
            b = best.get(g, {}).get(r.strategy, {})
            row = [f'<td class="l">{_e(r.label)} <span class="mut">{_e(json.dumps(b.get("params", {}), ensure_ascii=False))}'
                   f' {_e(FILTER_CN.get(b.get("filter", ""), ""))}</span></td>', f"<td>{int(x['events'].max())}</td>"]
            for h in DECAY_H:
                if h not in x.index:
                    row.append("<td>–</td>")
                    continue
                v = x.loc[h]
                cls = ' class="b"' if h == peak else ""
                row.append(f'<td{_bg(v.exp_bps, 60)} title="胜率 {pct(v.win_rate, 0)} t={num(v.t, 1)} R={num(v.exp_R, 2)}">'
                           f'<span{cls}>{num(v.exp_bps, 0)}</span></td>')
            drows.append(row)
        dtbl = _table(["策略（全样本最佳参数）", "信号数"] + [f"{h}h" for h in DECAY_H], drows)

        panes[g] = (f'<p class="mut">{_e(GROUP_NOTE.get(g, ""))}</p>'
                    f"<h3>策略表现（样本外，同类合并，按期望 R 排序）</h3>{tbl}"
                    '<h3>按行情状态拆分</h3><p class="mut">样本外交易按开仓时的行情状态分组的每笔期望（基点），括号内为笔数。'
                    '同一策略在不同行情下差别很大时，说明应该只在对应行情下使用。</p>' + rtbl +
                    '<h3>持仓时间曲线</h3><p class="mut">信号出现后，从下一根开盘起持有 N 小时的每笔平均收益（已扣一来一回成本，基点）。'
                    '加粗为最佳持有期。曲线先升后降说明优势会衰减，应在峰值附近离场。</p>' + dtbl)
    parts.append("<h2>分类明细</h2>" + _tabs("grp", panes))

    exits = "".join(f"<li><code>{_e(k)}</code> {_e(EXIT_CN[k])}：{_e(v or '仅信号')}</li>" for k, v in CLASS_EXITS.items())
    parts.append(f"""<h2>方法</h2><div class="card"><ul>
<li>每类只测为它设计的策略；参数、出场方式、行情过滤在全类所有标的上共用一套，同类标的的交易合并统计。</li>
<li>时间切成：前 40% 只用来挑配置，后 60% 分 3 段；每段开始前只用此前已平仓的交易挑配置（打分 = R 倍数的 t 值，至少 30 笔），再拿去跑这一段。</li>
<li>R 倍数 = 单笔收益 ÷ 开仓时 1 小时 ATR 占价格比例，让黄金和 MSTR 这种波动差很多的标的可以放在一起比。</li>
<li>行情状态：72 小时效率比（单边程度）与 24 小时波动，各自和本标的过去 90 天比较取分位；只用当时以前的数据。</li>
<li>出场方式（参与选择）：<ul>{exits}</ul></li>
<li>新闻冲击：1 小时涨跌超过平时波动 k 倍视为突发事件。这里看不到新闻内容，只统计事件后价格是延续还是回吐。</li>
<li>美股和能源合约只有几个月数据，结论只能作为方向参考；本报告不构成投资建议。</li></ul></div>""")

    title = "分类策略研究"
    if fragment:
        page = f'<title>{title}</title><style>{CSS}h3{{font-size:15px;margin:22px 0 6px}}</style><main>{"".join(parts)}</main><script>{JS}</script>'
        out = run_dir / "class_report_artifact.html"
    else:
        page = (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}h3{{font-size:15px;margin:22px 0 6px}}</style>'
                f'</head><body><main>{"".join(parts)}</main><script>{JS}</script></body></html>')
        out = run_dir / "class_report.html"
    out.write_text(page, encoding="utf-8")
    return out
