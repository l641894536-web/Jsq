(() => {
"use strict";
// 查个股（A股）：成长、增速变化、近120天强弱，结合当前牛熊给回测倾向（research/ashare_pick_bt.py）
const $ = (id) => document.getElementById(id);
let DATA = null, loading = null;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pc = (x) => (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(Math.abs(x) >= 10 ? 0 : 1) + "%";
const rk = (r) => r >= 0.5 ? `排前 ${Math.max(1, Math.round((1 - r) * 100))}%` : `排后 ${Math.max(1, Math.round(r * 100))}%`;
async function load() {
  if (DATA) return DATA;
  if (!loading) loading = fetch("stocks_a.json?d=" + new Date().toISOString().slice(0, 10)).then((r) => r.ok ? r.json() : null).then((d) => {
    if (!d) return null;
    const F = d.fields; d.objs = d.rows.map((r) => Object.fromEntries(F.map((k, i) => [k, r[i]]))); DATA = d; return d;
  }).catch(() => null);
  return loading;
}
function summary() {
  const s = (window.JSQ_ENV || {}).stocks_a;
  if (!s) { $("stkNote").textContent = "成长数据还在准备，稍后再看。"; return; }
  $("stkSub").textContent = `财报按公告日算 · ${s.date}`;
  $("stkNote").innerHTML = `现在可选的 ${s.n_uni} 只股票（正常交易、非ST、上市满一年、日均成交 3000 万以上）里，<b>"净利润增速前30% 且增速在加快"</b>的有 ${s.n_pool} 只，最多的行业：${s.pool_ind.slice(0, 5).map((x) => `${esc(x[0])} ${x[1]}`).join("、")}。`;
}
function search(q) {
  q = q.trim(); const box = $("stkList");
  if (!q || !DATA) { box.innerHTML = ""; return; }
  const digits = /^\d+$/.test(q);
  const hit = DATA.objs.filter((o) => digits ? o.code.startsWith(q) : (o.name || "").includes(q)).slice(0, 8);
  box.innerHTML = hit.length ? hit.map((o) => `<button type="button" data-c="${o.code}"><b>${esc(o.name || o.code)}</b><span>${o.code} · ${esc(o.ind || "")}</span></button>`).join("") : `<p class="note">没找到。</p>`;
}
function show(code) {
  const o = DATA.objs.find((x) => x.code === code); if (!o) return;
  $("stkList").innerHTML = "";
  const bull = (DATA.regime || "").startsWith("牛"), L = [];
  const g = o.growth, gtxt = Number.isFinite(g) ? `${pc(g)}（${rk(o.g_r)}）` : "没有数据";
  const acc = Number.isFinite(o.accel) ? `比上一期${o.accel >= 0 ? "加快" : "放慢"} ${Math.abs(o.accel * 100).toFixed(0)} 个百分点（${rk(o.a_r)}）` : "";
  L.push(`<p><b>成长</b>：最新已公告（${o.stat || "—"}）归母净利润同比 ${gtxt}${acc ? "，" + acc : ""}。${Number.isFinite(o.roe) ? `ROE ${(o.roe * 100).toFixed(1)}%。` : ""}</p>`);
  L.push(`<p><b>强弱</b>：近120天（不含最近一周）${Number.isFinite(o.mom120) ? `${pc(o.mom120)}（${rk(o.m_r)}）` : "—"}；近20天 ${Number.isFinite(o.mom20) ? pc(o.mom20) : "—"}。</p>`);
  if (o.bs != null) {
    const up = Number.isFinite(o.bup) ? pc(o.bup) : "—", mb = DATA.mbounce;
    const T = {
      0: `没有深跌（离一年高点不到 30%，或这轮低点已经过去很久），不用纠结反弹还是反转。`,
      1: `<b class="bad">深跌中，还没有像样的反弹</b>（比这轮低点高 ${up}）。等它从低点涨回 15% 再看下一步。`,
      2: `<b>第一波反弹</b>（现在比这轮低点高 ${up}）。历史上这种情况之后半年有 <b>45%</b> 会再跌破前低——一半一半，<b>不能当反转</b>。套着的可以先减一部分。${mb ? "" : `现在大盘自己没在反弹、是它单独在弹：这种再破低的有 54%，之后60天平均跑输大盘 2.3%，更该减。`}`,
      3: `<b class="ok">已二次确认</b>（回踩没破前低，又涨过了反弹高点；现在比低点高 ${up}）。之后半年再破前低的只有 <b>${o.a200 ? "23%" : "28%"}</b>${o.a200 ? "（它还站上了200日线）" : ""}。之前减掉的可以考虑接回。`,
      4: `<b class="bad">反弹后又跌破了前低</b>：这一轮只是反弹。卖掉的不用接回，等它重新走出"反弹 → 回踩不破 → 过前高"。`,
    }[o.bs];
    if (T) L.push(`<p><b>反弹还是反转</b>：${T}</p>`);
  }
  const hb = habit(o); if (hb) L.push(hb);
  const tips = [];
  if (!o.uni) tips.push("成交太小、上市不满一年、ST 或财报太旧，不在回测统计范围里，下面的倾向只作参考。");
  if (bull) {
    if (o.pool) tips.push(`<b class="ok">在"高成长+增速加快"池子里</b>：牛市里这类股票之后60天平均跑赢全市场约 0.9%（2021-05~2026-10，43个月里28个月跑赢；前半段只有+0.2%，后半段+1.6%）。`);
    else if (o.g_r >= 0.7) tips.push("成长快但增速在放慢：牛市里单看高成长，之后60天平均跑赢约 1.5%。");
    else tips.push("不在高成长那一档：回测里成长靠后的股票没有超额。");
    if (o.m_r <= 0.3) tips.push(`<b class="bad">近120天跌幅排在后30%</b>：牛市里这类股票之后60天平均跑输约 1.1%（2016–2026，10年里9年跑输），别急着抄底。`);
  } else {
    tips.push(`现在 A 股是<b>熊市</b>（等权指数在200日线下）：回测里成长股池子在熊市不跑赢（60天 −1.7%，只有两段熊市、样本少）。`);
    if (o.m_r >= 0.7) tips.push("这只近120天偏强：熊市里强势股 2021 年以后之后60天平均跑输约 2.2%，但 2016–2020 年没有这个规律。");
    else if (o.m_r <= 0.3) tips.push("这只近120天跌得多：熊市里跌多了的股票 2021 年以后之后60天平均跑赢约 2.4%，但 2016–2020 年不成立。");
    if (o.pool) tips.push(`它在"高成长+增速加快"池子里：等大盘重新站上200日线（转牛）再看，牛市里这个池子60天平均跑赢约 0.9%；熊市里它不跑赢（−0.1%）。`);
  }
  $("stkOut").innerHTML = `<div class="stk-h"><b>${esc(o.name || o.code)}</b><span>${o.code} · ${esc(o.ind || "")}</span></div>${L.join("")}<p class="stk-live" id="stkLive"></p><div class="stk-tip">${tips.map((t) => `<p>${t}</p>`).join("")}</div>
    <p class="note">统计倾向，不是买卖信号。"反弹还是反转"按 2020–2026 年 A 股 3 万次深跌反弹统计（跌 30% 以上、从低点涨回 15%），前后两段一致。</p>`;
  liveOpen(o);
}
// 开盘习惯（research/ashare_gap_bt.py）：同类股票近5年 + 这只自己近一年；单只的习惯基本不延续，以同类为准
const boardOf = (c) => c.startsWith("688") ? "科创板" : c.startsWith("30") ? "创业板" : "主板";
const p2 = (x) => (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(2) + "%";
function catOf(o) { const R = (window.JSQ_ENV || {}).gap_research; if (!R || !o.vq) return null; return R.cat[`${boardOf(o.code)}|${o.vq}`] || null; }
function habit(o) {
  const C = catOf(o); if (!C && !o.gu_n && !o.gd_n) return "";
  const R = window.JSQ_ENV.gap_research, VQ = ["", "最小", "偏小", "中等", "偏大", "最大"];
  let t = `<p><b>开盘习惯</b>：`;
  if (C) t += `同类（${boardOf(o.code)}、波动${VQ[o.vq]}的五分之一）近5年：<b>高开</b> 2%~7% 后 ${Math.round(C.up_fade * 100)}% 收在开盘下方，开盘后比大盘平均 ${p2(C.up_x)}；<b>低开</b> 2%~7% 后 ${Math.round(C.dn_rise * 100)}% 收在开盘上方，比大盘平均 ${p2(C.dn_x)}。`;
  if (o.gu_n || o.gd_n) t += `它自己近一年：高开 ${o.gu_n} 次、${o.gu_f} 次收在开盘下方；低开 ${o.gd_n} 次、${o.gd_f} 次收在开盘上方（单只股票自己的习惯下一年基本不重复，前后两段相关只有 0.1，以同类为准）。`;
  t += `</p>`;
  if (o.ztk > 0) {
    const ph = (window.JSQ_ENV.a.today || {}).phase, P = ph && R.phase[ph], Z = R.zt[o.ztk >= 2 ? "昨天连板" : "昨天首板"];
    t += `<p><b class="bad">${DATA.date.slice(5)} 涨停${o.ztk >= 2 ? `（${o.ztk}连板）` : ""}</b>：下一个交易日如果高开，${o.ztk >= 2 ? "连板" : "首板"}股历史上开盘后比大盘再差 ${p2(-Z.up_x).replace("+", "")}${P ? `；现在情绪在${ph}，涨停次日平均高开 ${p2(P.zt_gap)}、开盘后 ${p2(P.zt_oc)}` : ""}。想卖就在开盘附近卖。</p>`;
  }
  return t;
}
function loadQ(url) {
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = url; s.charset = "gbk"; s.async = true;
    const t = setTimeout(() => { s.remove(); rej(new Error("timeout")); }, 8000);
    s.onload = () => { clearTimeout(t); s.remove(); res(); }; s.onerror = () => { clearTimeout(t); s.remove(); rej(new Error("load")); };
    document.head.appendChild(s); });
}
async function liveOpen(o) {
  const box = $("stkLive"); if (!box) return;
  const sym = (o.code.startsWith("6") ? "sh" : "sz") + o.code;
  try {
    await loadQ("https://qt.gtimg.cn/q=" + sym);
    const v = window["v_" + sym]; try { delete window["v_" + sym]; } catch (e) {}
    if (typeof v !== "string") throw new Error("none");
    const f = v.split("~"), price = +f[3], prev = +f[4], open = +f[5], stamp = f[30] || "";
    if (!(prev > 0) || !(open > 0)) { box.innerHTML = `<b>今天</b>：还没开盘或停牌。`; return; }
    const lim = sym.startsWith("sh688") || sym.startsWith("sz30") ? 0.2 : 0.1;
    const upL = Math.floor(prev * (1 + lim) * 100 + 0.5) / 100, dnL = Math.floor(prev * (1 - lim) * 100 + 0.5) / 100;
    const g = open / prev - 1, now = price / open - 1, C = catOf(o);
    const day = /^\d{14}$/.test(stamp) ? `${+stamp.slice(4, 6)}月${+stamp.slice(6, 8)}日` : "今天";
    const after = +stamp.slice(8, 12) >= 1500 ? "收盘" : "现价";
    let t = `<b>${day}开盘 ${p2(g)}</b>，${after}比开盘 ${p2(now)}。`;
    if (Math.abs(open - upL) < 0.005) t += "开盘就涨停：多数（73%）能封到收盘。";
    else if (Math.abs(open - dnL) < 0.005) t += "开盘就跌停。";
    else if (g >= 0.02 && g < 0.07) t += `高开：同类历史上 ${C ? Math.round(C.up_fade * 100) : 55}% 收在开盘下方。想卖的话开盘附近卖不吃亏；想买的话不急。`;
    else if (g <= -0.02 && g > -0.07) t += `低开：同类历史上 ${C ? Math.round(C.dn_rise * 100) : 54}% 收在开盘上方，平均比大盘好 ${C ? Math.abs(C.dn_x * 100).toFixed(2) + "%" : "0.5%"}。想买的话开盘附近买平均更便宜；手里的别在开盘砍。`;
    else if (Math.abs(g) < 0.02) t += "开盘没有大幅跳空，这条规律用不上。";
    else t += "跳空超过 7%，样本少，不套用。";
    box.innerHTML = t;
  } catch (e) { box.textContent = ""; }
}
function init() {
  const q = $("stkQ"); if (!q) return;
  const go = () => load().then(() => search(q.value));
  q.addEventListener("focus", () => load());
  q.addEventListener("input", go);
  $("stkList").addEventListener("click", (e) => { const b = e.target.closest("button[data-c]"); if (b) { q.value = b.querySelector("b").textContent; show(b.dataset.c); } });
  if (window.JSQ_ENV) summary();
  document.addEventListener("jsq-env-ready", summary);
}
init();
})();
