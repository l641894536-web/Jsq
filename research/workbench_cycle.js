(() => {
"use strict";
// 正股页：A股短线情绪周期 + 高开低走规律（2026-11-13，research/ashare_cycle_bt.py、research/ashare_gap_bt.py）
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ab = (x, d = 2) => x == null || !isFinite(x) ? "—" : Math.abs(x * 100).toFixed(d) + "%";
const pc = (x, d = 1) => x == null || !isFinite(x) ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(d) + "%";
const ORDER = ["冰点", "低位回升", "中高位升温", "高潮", "中高位退潮", "低位回落"];
const COL = { "冰点": "#5B8FCB", "低位回升": "#9EBCE0", "中高位升温": "#EFB98F", "高潮": "#D9574A", "中高位退潮": "#E89B6C", "低位回落": "#B7C3D0" };
const phaseOf = (t, p5) => t < 20 ? "冰点" : t >= 80 ? "高潮" : t < 50 ? (t > p5 ? "低位回升" : "低位回落") : (t > p5 ? "中高位升温" : "中高位退潮");

function advice(ph, R) {
  const P = R.phase[ph], z = (x) => pc(x, 2);
  const zt = `涨停的票第二天平均高开 ${pc(P.zt_gap)}，开盘后再走 ${z(P.zt_oc)}（近5年前后两段 ${z(P.zt_oc_h[0])}/${z(P.zt_oc_h[1])}，2016–21 ${z(P.zt_oc_h[2])}）`;
  const f20 = `之后20天全A平均 ${pc(P.f20)}（${Math.round(P.f20_up * 100)}% 的时候上涨）`;
  return {
    "冰点": [["分批买", `${f20}，前后两段和2016–21都是正的，是唯一稳定的买点。`], ["涨停的票可以拿到收盘", zt + "。"], ["低开的票开盘就买", `这一段低开2%~7%的票，开盘后比大盘平均好 ${ab(P.lo_x)}。`]],
    "低位回升": [["别追高开", `高开的票 ${Math.round(P.hi_fade * 100)}% 收在开盘下方，比大盘平均差 ${ab(P.hi_x)}。`], ["少动", `${f20}，没有方向。`], ["涨停次日", zt + "，拿和卖差不多。"]],
    "中高位升温": [["涨停的票第二天开盘卖", zt + "。"], ["高开就减", `高开的票 ${Math.round(P.hi_fade * 100)}% 收在开盘下方。想减仓的，高开时在开盘附近减。`], ["拿着的别急", `${f20}。`]],
    "高潮": [["涨停的票第二天开盘就卖", zt + "，三段都一样，是最稳的一条。"], ["不追", `${f20}，前后两段一正一负；温度过热（80以上）之后60天平均是跌的。`], ["高开就减", `高开的票 ${Math.round(P.hi_fade * 100)}% 收在开盘下方。`]],
    "中高位退潮": [["涨停的票第二天开盘卖", zt + "。"], ["不加仓", `${f20}，看不出方向；退潮之后5天里 39% 会再升温、32% 落到低位。`]],
    "低位回落": [["少动，等冰点", `${f20}。等温度跌到20以下再分批买。`], ["要买就挑低开", `低开2%~7%的票开盘后比大盘平均好 ${ab(P.lo_x)}，想买的票等它低开、在开盘附近买。`], ["涨停次日", zt + "。"]],
  }[ph];
}

function ring(cur, trail) {
  const cx = 160, cy = 112, r = 74, sw = 18, n = 6, gapA = 2.2;
  const pt = (a, rr) => [cx + rr * Math.cos(a * Math.PI / 180), cy + rr * Math.sin(a * Math.PI / 180)];
  let out = "";
  ORDER.forEach((p, i) => {
    const a0 = -90 + i * 60 + gapA, a1 = -90 + (i + 1) * 60 - gapA, on = p === cur;
    const [x0, y0] = pt(a0, r), [x1, y1] = pt(a1, r);
    out += `<path d="M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}" fill="none" stroke="${COL[p]}" stroke-width="${on ? sw + 6 : sw}" stroke-opacity="${on ? 1 : 0.3}"/>`;
    const am = -90 + i * 60 + 30, [lx, ly] = pt(am, r + 30);
    const anchor = Math.abs(Math.cos(am * Math.PI / 180)) < 0.2 ? "middle" : Math.cos(am * Math.PI / 180) > 0 ? "start" : "end";
    out += `<text x="${lx.toFixed(1)}" y="${(ly + 4).toFixed(1)}" text-anchor="${anchor}" class="cy-lab${on ? " on" : ""}">${p}</text>`;
  });
  const ci = ORDER.indexOf(cur), [mx, my] = pt(-90 + ci * 60 + 30, r);
  out += `<circle cx="${mx.toFixed(1)}" cy="${my.toFixed(1)}" r="7" fill="var(--panel)" stroke="var(--ink)" stroke-width="2.5"/>`;
  return `<svg viewBox="0 0 320 224" class="cy-ring" role="img" aria-label="情绪周期：现在在${cur}">${out}</svg>`;
}

function render() {
  const E = window.JSQ_ENV; if (!E || !$("cyclePanel")) return;
  const R = E.gap_research, a = E.a.today, AL = window.JSQ_LIVE_A;
  if (!R || !R.phase) { $("cycleBody").innerHTML = `<p class="note">情绪周期数据还在准备。</p>`; return; }
  const ser = (E.a.series || []).filter((x) => x.t != null);
  const live = AL && AL.temp != null && ser.length && ser[ser.length - 1].d < new Date(AL.at + 8 * 3600e3).toISOString().slice(0, 10);
  const t = live ? AL.temp : a.temp;
  const base = live ? ser.slice(-5) : ser.slice(-6, -1);
  const p5 = base.length ? base.reduce((s, x) => s + x.t, 0) / base.length : a.t_prev5;
  const ph = live ? phaseOf(t, p5) : (a.phase || phaseOf(t, p5));
  // 最近12天的阶段
  const trail = [];
  for (let k = Math.max(5, ser.length - 12); k < ser.length; k++) { const b = ser.slice(k - 5, k); trail.push(phaseOf(ser[k].t, b.reduce((s, x) => s + x.t, 0) / b.length)); }
  if (live) trail.push(ph);
  const P = R.phase[ph], adv = advice(ph, R) || [], tr = (R.trans5 || {})[ph] || {};
  const nxt = Object.entries(tr).filter(([, v]) => v >= 8).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${k} ${v}%`).join("、");
  $("cycleSub").textContent = live ? "盘中估算" : `${+a.date.slice(5, 7)}月${+a.date.slice(8, 10)}日收盘`;
  const dd = `${+a.date.slice(5, 7)}月${+a.date.slice(8, 10)}日`;
  const kv = [["温度", `${Math.round(t)}`, `前5天平均 ${Math.round(p5)}`], ["涨停", a.zt, `跌停 ${a.dt}`], ["炸板率", a.zbl != null ? Math.round(a.zbl * 100) + "%" : "—", "冲板又打开"],
    ["连板高度", a.lb, "最高几连板"], ["涨停次日", a.prem != null ? pc(a.prem) : "—", "前一天涨停的"]];
  $("cycleBody").innerHTML = `
    <div class="cy-top">${ring(ph, trail)}
      <div class="cy-mid"><b class="num">${Math.round(t)}</b><span>${ph}</span></div></div>
    <div class="cy-trail">${trail.map((p) => `<i style="background:${COL[p]}" title="${p}"></i>`).join("")}<span>近${trail.length}天 →</span></div>
    <dl class="cy-kv">${kv.map(([k, v, s]) => `<div><dt>${k}</dt><dd><b class="num">${v}</b><small>${s}</small></dd></div>`).join("")}</dl>
    <p class="note cy-src">${live ? "温度是盘中估算；其余是" : "都是"} ${dd} 收盘的数。</p>
    <p class="pk-k">现在是<b>${ph}</b>（温度${t < 20 ? "低于20" : t >= 80 ? "80以上" : (t < 50 ? "20–50" : "50–80") + "，" + (t > p5 ? "比前5天平均高" : "不高于前5天平均")}）。近5年这一段占 ${Math.round(P.share * 100)}% 的交易日，一般连着两三天。5个交易日后常见：${nxt || "—"}。</p>
    ${adv.map(([k, v]) => `<div class="pk-rule"><b>${k}</b><p>${v}</p></div>`).join("")}
    <h3 class="pk-h">高开低走、低开收高：哪个阶段都成立</h3>
    <div class="pk-rule"><b>个股：高开的多数收在开盘下方，低开的平均收高</b><p>高开 2%~7% 的票 ${Math.round(R.all.up_fade * 100)}% 收在开盘下方，开盘后比大盘平均差 ${ab(R.all.up_x)}（中位数 ${pc(R.all.up_med, 2)}）；平均数接近 0，是因为少数会一路冲到涨停。低开 2%~7% 的 ${Math.round(R.all.dn_rise * 100)}% 收在开盘上方，平均 ${pc(R.all.dn_oc, 2)}，比大盘好 ${ab(R.all.dn_x)}。近5年前后两段、2016–21 都一样。</p></div>
    <div class="pk-rule"><b>怎么用</b><p>想买的票：低开时开盘附近买，比等到收盘平均便宜约 0.5%。想卖的票：高开时开盘附近卖，多数时候卖得比收盘好。昨天涨停、今天又高开的：首板平均比大盘再差 ${ab(R.zt["昨天首板"].up_x)}，连板差 ${ab(R.zt["昨天连板"].up_x)}，最该开盘卖。</p></div>
    <div class="pk-rule"><b>整个市场一起高开不算</b><p>全A平均高开 0.5% 以上的日子（近5年 ${R.mkt.hi_days} 天），只有 ${Math.round(R.mkt.hi_fade * 100)}% 收在开盘下方，开盘后平均还涨 ${pc(R.mkt.hi_oc, 2)}。上证、沪深300 高开后收在开盘下方也只有一半左右。你感觉到的高开低走是个股层面的：比大盘开得高的票，开盘后跑输大盘。</p></div>
    <div class="pk-rule"><b>不是赚钱的短线方法</b><p>低开买进（T+1 只能明天卖），到明天收盘平均只有 +0.06%，和随便哪天买差不多。这条规律只用来挑买卖的时机，不用来单独做交易。</p></div>
    <details class="pk-more"><summary>六个阶段的数字</summary>${table(R)}</details>`;
}

function table(R) {
  const z = (x) => pc(x, 2);
  return `<table class="shadow-t link-t cy-t"><colgroup><col style="width:24%"><col><col><col><col></colgroup><thead><tr><th>阶段</th><th>涨停次日开盘后</th><th>高开股比大盘</th><th>低开股比大盘</th><th>之后20天</th></tr></thead><tbody>` +
    ORDER.map((p) => { const P = R.phase[p]; return `<tr><td><i class="cy-dot" style="background:${COL[p]}"></i>${p}<small>${Math.round(P.share * 100)}% 的日子</small></td><td class="n ${P.zt_oc < 0 ? "r" : "g"}">${z(P.zt_oc)}</td><td class="n r">${z(P.hi_x)}</td><td class="n g">${z(P.lo_x)}</td><td class="n">${z(P.f20)}</td></tr>`; }).join("") +
    `</tbody></table><p class="note">${esc(R.period)} 全A（不含北交所、ST）。阶段按今天收盘的温度定，数字是第二天（或之后20天）的。"比大盘"= 开盘后涨跌减去当天全部股票开盘后的平均。</p>`;
}

function init() {
  if (window.JSQ_ENV) render();
  document.addEventListener("jsq-env-ready", render);
  document.addEventListener("jsq-live", render);
}
init();
})();
