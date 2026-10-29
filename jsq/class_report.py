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


PATH_COLS = [("trend", "一路顺", True), ("fake", "先顺后大逆", False), ("direct", "直接逆", False)]


def _verdict(t) -> str:
    if t is None or not np.isfinite(t):
        return "–"
    return ("方向有用" if t >= 2 else "略好于随机" if t >= 1 else "方向反了" if t <= -2 else
            "略差于随机" if t <= -1 else "跟随机差不多")


def _path_section(pt: pd.DataFrame, groups: list[str]) -> tuple[str, list[str]]:
    """方向与走向：不设止损，看开单后整条路怎么走、最后停在哪，与同一时刻随机开单比。"""
    panes, notes = {}, []
    r_atr = pt["R_atr"].iloc[0] if len(pt) else 2
    hz = int(pt["horizon_h"].iloc[0]) if len(pt) else 72
    for g in groups:
        x = pt[pt["group"] == g].sort_values("path_t", ascending=False)
        if not len(x):
            continue
        rows = []
        for r in x.to_dict("records"):
            row = [f'<td class="l">{_e(r["label"])} <span class="mut">{_e(r["strategy"])}</span></td>', f"<td>{int(r['n'])}</td>"]
            for k, _, high in PATH_COLS:
                v, b = r[f"p_{k}"], r[f"p_{k}_base"]
                row.append(f'<td{_bg((v - b) if high else (b - v), 0.08)}>{pct(v, 0)} <span class="mut">({pct(b, 0)})</span></td>')
            row.append(f"<td>{pct(r['p_flat'], 0)}</td>")
            v, b = r["p_fake3"] + r["p_direct3"], r["p_fake3_base"] + r["p_direct3_base"]
            row.append(f'<td{_bg(b - v, 0.08)}>{pct(v, 0)} <span class="mut">({pct(b, 0)})</span></td>')
            row.append(f'<td>{pct(r["end_ge2"], 0)} / {pct(r["end_le-2"], 0)} '
                       f'<span class="mut">({pct(r["end_ge2_base"], 0)} / {pct(r["end_le-2_base"], 0)})</span></td>')
            v = r.get("b3x2", np.nan)
            row.append(f'<td{_bg(v, 0.3)} title="止损 2 份、止盈 2 份：{num(r.get("b2x2", np.nan), 2)}">{num(v, 2)}</td>')
            for h in (24, 72, 168):
                v = r.get(f"hold{h}", np.nan)
                row.append(f'<td{_bg(v, 0.3)} title="涨（对信号方向有利）的比例 {pct(r.get(f"hold{h}_up", np.nan), 0)}">{num(v, 2)}</td>')
            row.append(f'<td class="l">{_verdict(r["path_t"])}</td>')
            rows.append(row)
        panes[g] = _table(["策略", "开单", "一路顺", "先顺后大逆", "直接逆", "没走出来", "途中跌到 −3R",
                           f"{hz // 24} 天后 ≥+2R / ≤−2R", "止损2份·止盈3份", "持有 1 天", "持有 3 天", "持有 7 天", "判断"], rows)
        good = [r["label"] for r in x.to_dict("records") if r["path_t"] >= 2]
        bad = [r["label"] for r in x.to_dict("records") if r["path_t"] <= -2]
        notes.append(f"<b>{_e(g)}</b>：方向有用的 {('、'.join(_e(v) for v in good)) or '没有'}；"
                     f"方向反了的 {('、'.join(_e(v) for v in bad)) or '没有'}；其余跟随机差不多或只略好/略差。")
    html = (f'<h2>方向与走向</h2><div class="card"><p>不设止损，看开单后 {hz // 24} 天内价格整条路怎么走。'
            f"1 份（R）= {num(r_atr, 0)} 倍 1 小时 ATR，大约是常用止损的距离。</p><ul>"
            "<li><b>一路顺</b>：先涨（空单是先跌）到 +2 份。</li>"
            "<li><b>先顺后大逆</b>：先往对的方向走了 0.8 份，没到 2 份就掉头，到了 −2 份。</li>"
            "<li><b>直接逆</b>：还没走出 0.8 份，就先到了 −2 份。</li>"
            f"<li><b>没走出来</b>：{hz // 24} 天里 ±2 份都没碰到。</li></ul>"
            '<p>括号里是同一时刻随机开单（波动完全一样）的比例。“先顺后大逆”和“直接逆”比随机还多，说明策略有问题；'
            "“止损2份·止盈3份”是按这个出场每笔平均赚几份（3 天没碰到就按收盘平）；“持有 N 天”是不设止损拿 N 天的平均盈亏（份）；都已扣成本。判断依据：好路径（一路顺）减坏路径"
            "（先顺后大逆、直接逆）相对随机的 t 值，≥2 算方向有用，≤−2 算方向反了。</p></div>"
            + _tabs("path", panes))
    return html, notes


def _screen_section(sc: pd.DataFrame, groups: list[str]) -> tuple[str, list[str]]:
    """先看方向的滚动筛选：按路径得分挑参数，下一段检验；含新加的突破类指标。"""
    from .path_screen import NEW_BREAKOUTS
    panes, notes = {}, []
    for g in groups:
        x = sc[sc["group"] == g].sort_values("path_t", ascending=False)
        if not len(x):
            continue
        rows = []
        for r in x.to_dict("records"):
            picks = json.loads(r["picks"]) if isinstance(r["picks"], str) else []
            last = picks[-1] if picks else {}
            same = len({json.dumps(p["params"], sort_keys=True) + p["filter"] for p in picks}) == 1 and len(picks) > 1
            cfg = (f'{_e(json.dumps(last.get("params", {}), ensure_ascii=False))} {_e(FILTER_CN.get(last.get("filter", ""), ""))}'
                   + ("（每段都选它）" if same else ""))
            new = ' <span class="b">新</span>' if r["strategy"] in NEW_BREAKOUTS else ""
            rows.append([f'<td class="l">{_e(r["label"])}{new} <span class="mut">{_e(r["strategy"])}</span></td>',
                         f"<td>{int(r['n'])}</td>", f'<td{_bg(r["path_t"], 3)}><b>{num(r["path_t"], 1)}</b></td>',
                         f'<td>{pct(r["trend"], 0)} <span class="mut">({pct(r["trend_b"], 0)})</span></td>',
                         f'<td>{pct(r["direct"], 0)} <span class="mut">({pct(r["direct_b"], 0)})</span></td>',
                         f'<td{_bg(r["bracket"], 0.3)}>{num(r["bracket"], 2)}</td>',
                         f'<td>{num(r["bracket_1"], 2)} / {num(r["bracket_2"], 2)}</td>',
                         f'<td{_bg(r["hold"], 0.3)}>{num(r["hold"], 2)}</td>', f'<td class="l">{cfg}</td>'])
        panes[g] = _table(["策略", "开单", "方向 t", "一路顺", "直接逆", "止损2份·止盈3份", "前段 / 后段", "拿满 3 天",
                           "最近一段选中的参数"], rows)
        ok = [r["label"] for r in x.to_dict("records") if r["path_t"] >= 2 and r["bracket"] > 0]
        notes.append(f"<b>{_e(g)}</b>：{('、'.join(_e(v) for v in ok)) or '没有过关的'}")
    html = ('<h2>先看方向：滚动筛选（含新指标）</h2><div class="card"><p>每段开始前，只用此前已经走完整条路的开单，'
            "按“一路顺多、先顺后大逆和直接逆少”（相对同一时刻随机开单）挑参数和行情过滤，再拿到下一段检验；"
            "表里是三段拼起来的样本外结果，单位是份（1 份 = 2 倍 1 小时 ATR），已扣成本。"
            "方向 t ≥ 2 且“止损2份·止盈3份”为正才算过关。标“新”的是这次新加的突破类指标。</p></div>" + _tabs("screen", panes))
    return html, notes


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
    pt_p = run_dir / "class_paths.csv"
    path_html = ""
    if pt_p.exists() and pt_p.stat().st_size > 10:
        path_html, notes = _path_section(pd.read_csv(pt_p), groups)
        items.append("<li><b>方向与走向</b>（不设止损看整条路，与随机开单比）：" + " ".join(notes) + "</li>")
    parts.append('<h2>结论摘要</h2><div class="card"><ul>' + "".join(items) + "</ul>"
                 '<p class="mut">判定标准：样本外 ≥30 笔、按 R 倍数的 t&gt;1.5、过半标的盈利。胜率低不要紧，'
                 '盈亏比 × 胜率决定期望。</p></div>')

    if path_html:
        parts.append(path_html)
    sc_p = run_dir / "class_screen.csv"
    if sc_p.exists() and sc_p.stat().st_size > 10:
        sc_html, sc_notes = _screen_section(pd.read_csv(sc_p), groups)
        parts.append(sc_html)
        parts[1] = parts[1].replace("</ul>", "<li><b>先看方向的滚动筛选</b>（过关 = 样本外方向 t≥2 且止损2份·止盈3份为正）："
                                    + "；".join(sc_notes) + "。</li></ul>", 1)

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

    # ---------- 新闻事件研究（newslab 输出时才有）
    ns_p = run_dir / "news_summary.csv"
    if ns_p.exists() and ns_p.stat().st_size > 10:
        ns = pd.read_csv(ns_p)
        npanes = {}
        for g in [x for x in GROUP_ORDER if x in set(ns["group"])]:
            x = ns[ns["group"] == g]
            rows = []
            for topic in x["topic"].unique():
                y = x[x["topic"] == topic].set_index("horizon_h")
                for key, label in (("follow_bps", "顺着新闻小时的方向"), ("tone_bps", "按情绪方向")):
                    tkey = "follow_t" if key == "follow_bps" else "tone_t"
                    r = [f'<td class="l">{_e(y["topic_cn"].iloc[0])}</td>', f'<td class="l">{label}</td>',
                         f"<td>{int(y['events'].max())}</td>"]
                    for h in [1, 2, 4, 8, 12, 24]:
                        if h not in y.index:
                            r.append("<td>–</td>")
                            continue
                        v = y.loc[h]
                        cls = ' class="b"' if abs(v[tkey]) > 2 else ""
                        r.append(f'<td{_bg(v[key], 60)} title="t={num(v[tkey], 1)}"><span{cls}>{num(v[key], 0)}</span></td>')
                    vr = y["vol_ratio"]
                    r.append(f"<td>{num(vr.get(4, np.nan), 1)}×</td>")
                    rows.append(r)
            npanes[g] = _table(["新闻主题", "做法", "事件数", "1h", "2h", "4h", "8h", "12h", "24h", "4h波动放大"], rows, left_cols=2)
        parts.append('<h2>新闻事件研究</h2><p class="mut">报道量超过过去 7 天均值 3 个标准差视为新闻突增（GDELT，新闻已延后 1 小时对齐）。'
                     '数字为事件后持有 N 小时的每笔平均收益（已扣成本，基点）；加粗为 |t|&gt;2。'
                     '“回吐反做”的收益约等于“顺势”取反再多扣一次成本。规则事先固定，未做参数优化。</p>' + _tabs("news", npanes))

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
