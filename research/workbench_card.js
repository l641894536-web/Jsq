(() => {
"use strict";
// 页面切换、顶部状态栏、合约"一眼看懂"结论卡、选品种、正股"一眼看懂"。方向只用回测过的规则下结论，技术面用大白话描述。
const $ = (id) => document.getElementById(id);
const U = window.JSQ_UNIVERSE;
const pct = (x, dp = 1) => (x == null || !isFinite(x)) ? "—" : (x >= 0 ? "+" : "") + (x * 100).toFixed(dp) + "%";
const pabs = (x, dp = 1) => (x == null || !isFinite(x)) ? "—" : (Math.abs(x) * 100).toFixed(dp) + "%";
const fmt = (x, dp) => (x == null || !isFinite(x)) ? "—" : Number(x).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const REST = "https://fapi.binance.com";
const DMA = {};            // sym -> { price, ma200, vs, bull, at }  日线200日线
let lastRender = 0, timer = null, lastKey = "";

// ================================================================ 页面切换
const TABS = ["today", "contract", "stock", "research"];
function setTab(t, push) {
  if (!TABS.includes(t)) t = "today";
  for (const k of TABS) { const el = $("tab-" + k); if (el) el.hidden = k !== t; }
  $("tabs").querySelectorAll("button").forEach((b) => { const on = b.dataset.tab === t; b.setAttribute("aria-selected", String(on)); b.setAttribute("aria-pressed", String(on)); });
  if (push) { try { history.replaceState(null, "", "#" + t); } catch (e) {} }
  try { localStorage.setItem("tab", t); } catch (e) {}
  document.dispatchEvent(new CustomEvent("jsq-tab", { detail: t }));
}
// 从今天页跳到某个品种：切到"品种"页、选中、滚到卡片（或卡片里的"我已经有仓位"）
function goSym(sym, where) {
  if (!window.JSQ || !U.all.includes(sym)) return;
  setTab("contract", true); window.JSQ.select(sym);
  requestAnimationFrame(() => { const c = $(where || "card"); if (where === "posBox" && c) c.open = true; if (c) c.scrollIntoView({ behavior: "smooth", block: "start" }); });
}
function initTabs() {
  $("tabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { setTab(b.dataset.tab, true); window.scrollTo({ top: 0 }); }));
  let t = (location.hash || "").replace("#", "");
  if (!TABS.includes(t)) t = "today";
  setTab(t, false);
  window.addEventListener("hashchange", () => { const h = location.hash.replace("#", ""); if (TABS.includes(h)) setTab(h, false); });
}

// ================================================================ 环境
function usNow() {
  const E = window.JSQ_ENV; if (!E) return null;
  const L = window.JSQ_LIVE_US, UL = E.live && E.live.us;
  if (L && UL && L.QQQ && UL.QQQ) {
    const ma = (UL.QQQ.sum199 + L.QQQ) / 200, sma = (UL.SPY.sum199 + L.SPY) / 200;
    return { bull: E.us.today.ndx_vs > 0, vs: L.QQQ / ma - 1, spxVs: L.SPY / sma - 1, live: true, stopDist: L.QQQ / UL.QQQ.stop_line - 1, stop: E.us.today.stop_line };
  }
  const u = E.us.today;
  return { bull: u.ndx_vs > 0, vs: u.ndx_vs, spxVs: u.spx_vs, live: false, stopDist: u.ndx / u.stop_line - 1, stop: u.stop_line };
}
// 日线200日线：贵金属/大宗按期货交易日（去掉周末K线），加密按自然日
async function fetchDMA(sym) {
  const r = await fetch(`${REST}/fapi/v1/klines?symbol=${sym}&interval=1d&limit=320`, { cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const k = await r.json();
  if (!Array.isArray(k) || k.length < 2) throw new Error("short");
  const price = +k[k.length - 1][4], crypto = U.groupOfSym(sym) === "crypto";
  const done = k.slice(0, -1).filter((x) => { if (crypto) return true; const d = new Date(+x[0]).getUTCDay(); return d !== 0 && d !== 6; }).map((x) => +x[4]).slice(-199);
  if (done.length < 199) throw new Error("short");
  const ma = (done.reduce((s, x) => s + x, 0) + price) / 200, ma50 = (done.slice(-49).reduce((s, x) => s + x, 0) + price) / 50;
  const ma50c = done.slice(-50).reduce((s, x) => s + x, 0) / 50, prevC = done[done.length - 1];
  DMA[sym] = { price, ma200: ma, vs: price / ma - 1, bull: price > ma, ma50, vs50: price / ma50 - 1, bull50: price > ma50, ma50c, bull50c: prevC > ma50c, at: Date.now() };
}
async function needDMA(sym) {
  if (DMA[sym] && Date.now() - DMA[sym].at < 5 * 60e3) return;
  try { await fetchDMA(sym); }
  catch (e) {
    // 币安上市不满200个交易日（铜、天然气等）：用美国期货日线的200日线
    const f = ((window.JSQ_ENV || {}).live || {}).fut, x = f && f[sym];
    if (x) DMA[sym] = { price: x.close, ma200: x.ma200, vs: x.vs, bull: x.vs > 0, at: Date.now(), src: `${x.ticker}期货 ${x.date.slice(5)} 收盘` };
  }
}
// 一个品种的"大方向"
// 非科技蓝筹（回测样本：23只金融/医药/消费/能源/工业大盘股）——大方向看标普，不看纳指
const NONTECH = ["JPMUSDT", "GSUSDT", "BACUSDT", "BXUSDT", "VUSDT", "LLYUSDT", "UNHUSDT", "ABBVUSDT", "MRKUSDT", "PFEUSDT", "AMGNUSDT",
  "COSTUSDT", "WMTUSDT", "HDUSDT", "MCDUSDT", "KOUSDT", "NKEUSDT", "DISUSDT", "XOMUSDT", "OXYUSDT", "CATUSDT", "ACNUSDT", "XLEUSDT", "SPYUSDT"];
function envFor(sym) {
  const g = U.groupOfSym(sym);
  if (g === "stock") {
    const u = usNow(); if (!u) return null;
    if (NONTECH.includes(sym)) {
      const b = u.spxVs > 0;
      return { bull: b, what: `标普在200日线${b ? "上方" : "下方"}（${pct(u.spxVs)}）`, src: u.live ? "币安SPY合约实时" : "上个美股收盘" };
    }
    return { bull: u.bull, what: `纳指上个收盘在200日线${u.bull ? "上方" : "下方"}（现在比200日线 ${pct(u.vs)}）`, src: u.live ? "牛熊按上个收盘，现价来自币安QQQ合约" : "上个美股收盘" };
  }
  const ref = g === "crypto" ? "BTCUSDT" : sym, d = DMA[ref];
  if (!d) return null;
  const nm = U.names[ref] || ref;
  // 币：方向看比特币50日线（比200日线好：线上突破做多 +0.21、线下跌破做空 +0.18 份/笔，7个币都成立）
  // 黄金白银：2026-11-11 起看自身50日线（上个收盘），回测 research/metals50_stats.py：50日线上方突破做多 黄金+0.38R、白银+0.20R/笔，和200日线差不多，但能早得多回到可做状态
  if ((ref === "XAUUSDT" || ref === "XAGUSDT") && isFinite(d.ma50c)) return { bull: d.bull50c, what: `${nm}收盘在50日线${d.bull50c ? "上方" : "下方"}（现价比50日线${pct(d.vs50)}）`, src: d.src || "币安日线", m50: true, lbl: `${nm}在50日线${d.bull50c ? "上方" : "下方"}` };
  if (g === "crypto" && isFinite(d.vs50)) return { bull: d.bull50, what: `${nm}在50日线${d.bull50 ? "上方" : "下方"}（${pct(d.vs50)}）`, src: d.src || "币安日线实时", w50: true };
  return { bull: d.bull, what: `${nm}在200日线${d.bull ? "上方" : "下方"}（${pct(d.vs)}）`, src: d.src || "币安日线实时" };
}

// ================================================================ 状态栏
function sChip(id, text, cls) { const b = $(id); if (!b) return; b.querySelector("b").textContent = text; b.className = "schip " + (cls || ""); }
const band = (t) => t < 20 ? "冰点" : t < 40 ? "偏冷" : t <= 60 ? "中性" : t <= 80 ? "偏热" : "过热";
// ================================================================ 跑道图（今天页）：一条横道、一根基准线、一个点
// x 用 0..1。第一次画时点从左边滑进来，之后从上次的位置挪到新位置（只有这一个动效）
const LANEX = {};
const pc100 = (x) => (Math.max(0, Math.min(1, x)) * 100).toFixed(2) + "%";
function trackHTML(o) {
  const z = (o.zones || []).map(([a, b, c]) => `<i class="ln-z ${c}" style="left:${pc100(a)};width:${pc100(b - a)}"></i>`).join("");
  const t = (o.ticks || []).map(([x, lb, c]) => `<i class="ln-l ${c || ""}" style="left:${pc100(x)}">${lb ? `<em>${lb}</em>` : ""}</i>`).join("");
  const prev = LANEX[o.key] != null ? LANEX[o.key] : 0.02; LANEX[o.key] = o.x;
  return `<span class="ln-t${o.tcls ? " " + o.tcls : ""}">${z}${t}<i class="ln-dot ${o.dot || ""}" style="left:${pc100(prev)}" data-x="${pc100(o.x)}"></i></span>`;
}
function laneHTML(o) {
  return `<button type="button" class="lane ${o.cls || ""}" ${o.sym ? `data-sym="${esc(o.sym)}"` : ""} ${o.go ? `data-go="${o.go}"` : ""}>` +
    `<span class="ln-n"><b>${esc(o.name)}</b>${o.small ? `<small>${o.small}</small>` : ""}</span>${trackHTML(o)}` +
    `<span class="ln-v"><b>${o.v || ""}</b>${o.vs ? `<small>${o.vs}</small>` : ""}</span>${o.note ? `<span class="ln-note">${o.note}</span>` : ""}</button>`;
}
function slideLanes(box) {
  requestAnimationFrame(() => requestAnimationFrame(() => box.querySelectorAll(".ln-dot[data-x]").forEach((d) => { d.style.left = d.dataset.x; })));
  box.querySelectorAll(".lane").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.sym) goSym(b.dataset.sym); else if (b.dataset.go) { setTab(b.dataset.go, true); window.scrollTo({ top: 0 }); }
  }));
}
function renderEnvLanes() {
  const box = $("envLanes"); if (!box) return;
  const E = window.JSQ_ENV, L = [], sc = (v, R) => 0.5 + Math.max(-1, Math.min(1, v / R)) * 0.46;
  const half = [[0, 0.5, "dn"], [0.5, 1, "up"]];
  const u = usNow();
  const usNote = u && (u.vs >= 0) !== u.bull ? `按上个收盘还是${u.bull ? "牛市" : "熊市"}；现在已经${u.vs >= 0 ? "回到线上" : "跌到线下"}，美股收盘还这样就转${u.bull ? "熊" : "牛"}` : "";
  if (u) L.push({ key: "e-us", go: "stock", name: "美股", small: "纳指", x: sc(u.vs, 0.12), zones: half, ticks: [[0.5, "200日线"]], dot: u.vs >= 0 ? "up" : "dn",
    v: `${u.bull ? "牛市" : "熊市"} <span class="num">${pct(u.vs)}</span>`, note: (u.bull ? "AMD/美光/戴尔：突破做多" : "AMD/美光/戴尔：只做大跌后止跌") + (usNote ? `<br><span class="warnc">${usNote}</span>` : "") });
  const b = DMA.BTCUSDT;
  if (b && isFinite(b.vs50)) L.push({ key: "e-btc", sym: "BTCUSDT", name: "比特币", small: "日线", x: sc(b.vs50, 0.15), zones: half, ticks: [[0.5, "50日线"]], dot: b.bull50 ? "up" : "dn",
    v: `${b.bull50 ? "线上" : "线下"} <span class="num">${pct(b.vs50)}</span>`, note: b.bull50 ? "7个币：突破做多" : "7个币：跌破做空" });
  for (const [sym, nm] of [["XAUUSDT", "黄金"], ["XAGUSDT", "白银"]]) {
    const m = DMA[sym]; if (!m || !isFinite(m.ma50c)) continue;
    L.push({ key: "e-" + sym, sym, name: nm, small: "日线", x: sc(m.vs50, 0.12), zones: half, ticks: [[0.5, "50日线"]], dot: m.vs50 >= 0 ? "up" : "dn",
      v: `${m.bull50c ? "线上" : "线下"} <span class="num">${pct(m.vs50)}</span>`, note: m.bull50c ? `${nm}：突破做多` : `${nm}：不做，等收盘站上 ${fmt(m.ma50, m.price >= 100 ? 0 : 2)}` });
  }
  if (E && E.a && E.a.today) {
    const a = E.a.today, AL = window.JSQ_LIVE_A, t = AL ? AL.temp : a.temp, reg = AL ? AL.regime : a.regime;
    L.push({ key: "e-a", go: "stock", name: "A股", small: "情绪温度", x: 0.02 + Math.max(0, Math.min(100, t)) / 100 * 0.96, tcls: "temp",
      ticks: [[0.212, ""], [0.404, ""], [0.596, ""], [0.788, ""]], dot: "ink", v: `${reg} · ${band(t)} <span class="num">${Math.round(t)}</span>`, note: "只作正股参考，不给合约信号" });
  }
  if (!L.length) { box.innerHTML = `<p class="note">正在载入…</p>`; return; }
  box.innerHTML = L.map(laneHTML).join(""); slideLanes(box);
}
function renderBar() {
  renderEnvLanes();
  const E = window.JSQ_ENV;
  if (E) {
    const a = E.a.today, AL = window.JSQ_LIVE_A;
    const t = AL ? AL.temp : a.temp, reg = AL ? AL.regime : a.regime;
    sChip("sbA", `${reg} · ${band(t)} ${Math.round(t)}`, reg === "牛市" ? "good" : "warn");
    const u = usNow();
    if (u) sChip("sbUS", `${u.bull ? "牛市" : "熊市"} · 纳指${pct(u.vs)}`, u.bull ? "good" : "warn");
  }
  for (const [sym, id] of [["XAUUSDT", "sbAU"], ["XAGUSDT", "sbAG"], ["BTCUSDT", "sbBTC"]]) {
    const m = DMA[sym];
    if (m && sym === "BTCUSDT" && isFinite(m.vs50)) sChip(id, `${m.bull50 ? "偏多" : "偏空"} · 50日线${pct(m.vs50)}`, m.bull50 ? "good" : "warn");
    else if (m && isFinite(m.ma50c)) sChip(id, `${m.bull50c ? "可做多" : "不做"} · 50日线${pct(m.vs50)}`, m.bull50c ? "good" : "warn");
    else if (m) sChip(id, `${m.bull ? "牛市" : "熊市"} · ${pct(m.vs)}`, m.bull ? "good" : "warn");
  }
}

// ================================================================ 技术面（大白话）
function tech(V, tf) {
  const t = V.n - 1, items = [], day = tf === "1d" ? "20日" : "24小时", dp = V.dp;
  let score = 0;
  const add = (k, lean, txt, s) => { items.push({ k, lean, txt }); score += s; };
  add("均线", V.trend === 1 ? "多" : "空", V.trend === 1 ? "短期均线在长期均线上面，趋势向上" : "短期均线在长期均线下面，趋势向下", V.trend);
  const h1 = V.hist[t], h0 = V.hist[t - 1], h3 = V.hist[t - 3];
  if (h1 > 0) add("MACD", "多", (h0 <= 0 || h3 <= 0) ? "刚翻红（金叉），上涨动能刚出来" : (h1 > h0 ? "红柱在变长，上涨在加速" : "红柱在变短，上涨在减速"), 1);
  else add("MACD", "空", (h0 >= 0 || h3 >= 0) ? "刚翻绿（死叉），下跌动能刚出来" : (h1 < h0 ? "绿柱在变长，下跌在加速" : "绿柱在变短，下跌在减速"), -1);
  const r = V.R[t];
  if (r == null) add("RSI", "中", "数据不够", 0);
  else if (r >= 70) add("RSI", "中", `${r.toFixed(0)}，超买：涨得太急，容易回落`, 0);
  else if (r >= 55) add("RSI", "多", `${r.toFixed(0)}，偏强`, 1);
  else if (r > 45) add("RSI", "中", `${r.toFixed(0)}，不强不弱`, 0);
  else if (r > 30) add("RSI", "空", `${r.toFixed(0)}，偏弱`, -1);
  else add("RSI", "中", `${r.toFixed(0)}，超卖：跌得太急，容易反弹`, 0);
  const H = V.H, L = V.L, last = V.last;
  let pos, pl = "中", ps = 0;
  if (isFinite(H) && last > H) { pos = `刚突破${day}最高点 ${fmt(H, dp)}`; pl = "多"; ps = 1; }
  else if (isFinite(L) && last < L) { pos = `刚跌破${day}最低点 ${fmt(L, dp)}`; pl = "空"; ps = -1; }
  else if (isFinite(H) && isFinite(L) && H > L) {
    const p = (last - L) / (H - L);
    pos = p > 0.75 ? `在${day}高点附近（离 ${fmt(H, dp)} 还差 ${pabs(H / last - 1, 2)}）` : p < 0.25 ? `在${day}低点附近（离 ${fmt(L, dp)} 还差 ${pabs(last / L - 1, 2)}）` : `在${day}高低点中间`;
  } else pos = "—";
  if (V.res[0] && (V.res[0].p - last) / V.a <= 0.6) pos += `，头上就是阻力 ${fmt(V.res[0].p, dp)}`;
  else if (V.sup[0] && (last - V.sup[0].p) / V.a <= 0.6) pos += `，脚下就是支撑 ${fmt(V.sup[0].p, dp)}`;
  add("位置", pl, pos, ps);
  if (V.regime === "bull") add("日线", "多", "日线在涨（站在50日均线上方且均线向上）", 1);
  else if (V.regime === "bear") add("日线", "空", "日线在跌（在50日均线下方且均线向下）", -1);
  else add("日线", "中", V.regime ? "日线在震荡" : "日线数据不够", 0);
  const pat = V.pats.filter((p) => p.status === "pending" || (p.status === "break" && p.at >= t - 6)).pop();
  if (pat) {
    const up = pat.side === 1;
    add("形态", up ? "多" : "空", pat.status === "pending" ? `${up ? "双底" : "双顶"}已成形，等收盘${up ? "站上" : "跌破"}颈线 ${fmt(pat.neck, dp)}` : `${up ? "双底刚突破" : "双顶刚跌破"}颈线 ${fmt(pat.neck, dp)}`, pat.status === "break" ? (up ? 1 : -1) : 0);
  }
  const lean = score >= 2 ? "偏多" : score <= -2 ? "偏空" : "多空分歧";
  return { items, score, lean };
}

// ================================================================ 结论卡
const STATKEY = { XAUUSDT: "XAUUSD", XAGUSDT: "XAGUSD", XPTUSDT: "commod", XPDUSDT: "commod", COPPERUSDT: "commod", NATGASUSDT: "commod" };
// 只有真在回测样本里的股票才用那一组的统计；样本外的（SPCX、PLTR、COIN……）一律算"没回测过"，不借别人的数
const TESTED_MAIN = ["AMDUSDT", "MUUSDT", "DELLUSDT"];
const TESTED_TECH = ["AAPL", "ADBE", "ADI", "AMAT", "AMZN", "AVGO", "CRM", "CSCO", "GOOGL", "IBM", "INTC", "INTU", "LRCX", "MRVL",
  "MSFT", "NFLX", "NVDA", "ORCL", "PYPL", "QCOM", "TSLA", "TXN"].map((x) => x + "USDT");
const TESTED_NONTECH = ["BA", "BAC", "COST", "CVX", "DIS", "GS", "HD", "JNJ", "JPM", "KO", "LLY", "MA", "MCD", "MRK", "NKE", "PEP",
  "PFE", "PG", "UNH", "V", "WFC", "WMT", "XOM"].map((x) => x + "USDT");
const TESTED_CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"];
function statKey(sym) {
  if (STATKEY[sym]) return STATKEY[sym];
  const cs = (window.JSQ_ENV || {}).contract_stats || {}, own = "sym_" + sym.replace(/USDT$/, "");
  if (cs[own]) return own;                       // 单只股票自己的5年小时线回测
  if (TESTED_CRYPTO.includes(sym)) return "crypto";
  if (TESTED_MAIN.includes(sym)) return "stock_main";
  if (TESTED_TECH.includes(sym)) return "stock_other";
  if (TESTED_NONTECH.includes(sym)) return "stock_nontech";
  return null;
}
function statFor(sym, bull, side) {
  const E = window.JSQ_ENV; if (!E || !E.contract_stats) return null;
  const key = statKey(sym);
  if (!key || !E.contract_stats[key]) return null;
  const s = E.contract_stats[key][`breakout|E|${bull ? "bull" : "bear"}|${side}`];
  return s ? { key, s, env: { bull }, side } : null;
}
const SAMPLE = { stock_main: "AMD/美光/戴尔近5年", stock_other: "22只大型科技股近5年", stock_nontech: "23只非科技蓝筹近5年", crypto: "7个主流币近5年", commod: "铂金/钯金/铜/天然气近5年",
  XAUUSD: "黄金近5年", XAGUSD: "白银近5年", XPTCMDUSD: "铂金近5年", XPDCMDUSD: "钯金近5年", COPPERCMDUSD: "铜近5年", GASCMDUSD: "天然气近5年" };
// 回测评级：样本少 / 稳定赚 / 时灵时不灵 / 基本不赚 / 亏
function grade(st) {
  if (!st) return "none";
  const s = st.s;
  if (s.n < (st.key.startsWith("sym_") ? 60 : 100)) return "few";
  if (s.avg >= 0.08) return st.key.startsWith("sym_") ? "few" : Math.min(s.h1, s.h2) >= 0.03 ? "edge" : "unstable";   // 单只股票的好成绩不延续（72只前后一年对比），不当依据
  return s.avg > -0.03 ? "flat" : "lose";
}
const rTxt = (x) => `${x >= 0 ? "赚" : "亏"}止损金额的${Math.round(Math.abs(x) * 100)}%`;
const uOf = (key, bull, side, v) => { const t = (((window.JSQ_ENV || {}).contract_stats || {})[key] || {})[`u|${bull ? "bull" : "bear"}|${side === 1 || side === "long" ? "long" : "short"}`]; return t && t[v || "F"] ? t[v || "F"] : null; };
const uTxt = (u) => `${u >= 0 ? "赚" : "亏"} ${Math.abs(u).toFixed(1)}U`;
const symMeta = (key) => key && key.startsWith("sym_") ? ((((window.JSQ_ENV || {}).contract_stats || {})[key] || {})._meta || null) : null;
const symNote = (st) => st && st.key.startsWith("sym_") ? "（单只股票自己的历史太短；查过72只这类股票，前一年突破灵的、后一年反而偏差，单只的成绩只能当参考。）" : "";
const ymTxt = (d) => `${d.slice(0, 4)}年${+d.slice(5, 7)}月`;
const halfTxt = (s, key) => { const m = symMeta(key);
  if (m && m.mid) return `${ymTxt(m.start)}到${ymTxt(m.mid)}平均每笔${rTxt(s.h1)}，之后${rTxt(s.h2)}`;
  return `2021-11到2024-04平均每笔${rTxt(s.h1)}，2024-05以后${rTxt(s.h2)}`; };
window.JSQ_STATKEY = statKey; window.JSQ_ENVFOR = (sym) => envFor(sym);
window.JSQ_PLAN = () => PLANNUM;
function histLine(st, label) {
  if (!st) return "";
  const s = st.s, w = Math.round(s.win * 10), net = s.avg;
  const m = symMeta(st.key), smp = SAMPLE[st.key] || (st.key.startsWith("sym_") ? `${st.key.slice(4)}自己${m ? "从" + ymTxt(m.start) + "起" : ""}的小时线` : st.key);
  const u = st.env ? uOf(st.key, st.env.bull, st.side, "F") : null;
  return `${label}：10笔里赚${w}笔，` + (u ? `按100U开5倍平均每次${uTxt(u.u)}` : `平均每笔${rTxt(net)}`) + `（${smp}，${s.n}笔）`;
}
function usMarketClosed() {
  const p = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
  const g = (t) => (p.find((x) => x.type === t) || {}).value;
  const wd = g("weekday"), hm = (+g("hour") % 24) * 60 + +g("minute");
  return wd === "Sat" || wd === "Sun" || hm < 9 * 60 + 30 || hm >= 16 * 60;
}
// 出场方式回测（research/exit_bt.py）：同一进场，按品种×环境×方向比较
// F=1R保本+跟踪3天低点（不设固定止盈） G=固定2R全平 B=1R先平一半 J=2R先平一半+剩下跟踪3天低点 A=只放初始止损
const EXIT = {"stock_main":{"bear|long":{"F":{"n":69,"avg":0.113,"win":39,"h1":-0.074,"h2":1.001},"G":{"n":77,"avg":0.048,"win":31,"h1":-0.104,"h2":0.794},"B":{"n":78,"avg":0.098,"win":53,"h1":-0.038,"h2":0.848},"J":{"n":69,"avg":0.139,"win":41,"h1":-0.028,"h2":0.935},"A":{"n":61,"avg":0.217,"win":38,"h1":-0.083,"h2":1.44}},"bear|short":{"F":{"n":79,"avg":-0.171,"win":32,"h1":-0.13,"h2":-0.38},"G":{"n":78,"avg":0.007,"win":29,"h1":0.057,"h2":-0.243},"B":{"n":88,"avg":-0.14,"win":42,"h1":-0.112,"h2":-0.28},"J":{"n":79,"avg":-0.143,"win":33,"h1":-0.111,"h2":-0.307},"A":{"n":62,"avg":0.043,"win":34,"h1":-0.041,"h2":0.479}},"bull|long":{"F":{"n":261,"avg":0.284,"win":36,"h1":0.286,"h2":0.283},"G":{"n":310,"avg":0.155,"win":32,"h1":0.245,"h2":0.106},"B":{"n":313,"avg":0.135,"win":51,"h1":0.151,"h2":0.126},"J":{"n":261,"avg":0.213,"win":38,"h1":0.262,"h2":0.181},"A":{"n":222,"avg":0.386,"win":35,"h1":0.437,"h2":0.354}},"bull|short":{"F":{"n":196,"avg":-0.263,"win":23,"h1":-0.373,"h2":-0.193},"G":{"n":216,"avg":-0.254,"win":20,"h1":-0.297,"h2":-0.227},"B":{"n":220,"avg":-0.203,"win":40,"h1":-0.273,"h2":-0.161},"J":{"n":196,"avg":-0.228,"win":26,"h1":-0.313,"h2":-0.175},"A":{"n":165,"avg":-0.298,"win":24,"h1":-0.424,"h2":-0.224}}},"stock_other":{"bear|long":{"F":{"n":537,"avg":0.034,"win":35,"h1":-0.059,"h2":0.395},"G":{"n":594,"avg":0.03,"win":32,"h1":-0.034,"h2":0.295},"B":{"n":624,"avg":-0.018,"win":50,"h1":-0.064,"h2":0.179},"J":{"n":537,"avg":0.017,"win":37,"h1":-0.05,"h2":0.277},"A":{"n":495,"avg":-0.018,"win":29,"h1":-0.157,"h2":0.512}},"bear|short":{"F":{"n":608,"avg":-0.057,"win":33,"h1":-0.009,"h2":-0.26},"G":{"n":694,"avg":-0.028,"win":27,"h1":-0.012,"h2":-0.095},"B":{"n":702,"avg":-0.052,"win":46,"h1":-0.048,"h2":-0.069},"J":{"n":608,"avg":-0.02,"win":34,"h1":0.009,"h2":-0.139},"A":{"n":514,"avg":0.001,"win":31,"h1":0.034,"h2":-0.145}},"bull|long":{"F":{"n":1869,"avg":0.051,"win":34,"h1":0.048,"h2":0.053},"G":{"n":2153,"avg":0.026,"win":33,"h1":0.029,"h2":0.024},"B":{"n":2175,"avg":0.024,"win":50,"h1":0.042,"h2":0.013},"J":{"n":1869,"avg":0.046,"win":37,"h1":0.026,"h2":0.06},"A":{"n":1625,"avg":0.077,"win":33,"h1":0.16,"h2":0.018}},"bull|short":{"F":{"n":1540,"avg":-0.097,"win":30,"h1":-0.119,"h2":-0.082},"G":{"n":1717,"avg":-0.09,"win":26,"h1":-0.106,"h2":-0.081},"B":{"n":1744,"avg":-0.071,"win":46,"h1":-0.073,"h2":-0.07},"J":{"n":1540,"avg":-0.077,"win":32,"h1":-0.093,"h2":-0.066},"A":{"n":1368,"avg":-0.109,"win":28,"h1":-0.193,"h2":-0.054}}},"XAGUSD":{"bear|long":{"F":{"n":68,"avg":0.063,"win":37,"h1":0.145,"h2":-0.183},"G":{"n":78,"avg":0.056,"win":36,"h1":0.099,"h2":-0.086},"B":{"n":72,"avg":0.004,"win":40,"h1":0.052,"h2":-0.142},"J":{"n":68,"avg":0.076,"win":38,"h1":0.153,"h2":-0.152},"A":{"n":68,"avg":0.071,"win":37,"h1":0.153,"h2":-0.175}},"bear|short":{"F":{"n":64,"avg":-0.027,"win":27,"h1":-0.084,"h2":0.16},"G":{"n":73,"avg":-0.083,"win":27,"h1":-0.126,"h2":0.038},"B":{"n":74,"avg":-0.079,"win":38,"h1":-0.143,"h2":0.153},"J":{"n":64,"avg":-0.05,"win":28,"h1":-0.123,"h2":0.188},"A":{"n":63,"avg":-0.033,"win":30,"h1":-0.095,"h2":0.167}},"bull|long":{"F":{"n":124,"avg":0.213,"win":28,"h1":-0.041,"h2":0.343},"G":{"n":154,"avg":0.114,"win":31,"h1":-0.07,"h2":0.21},"B":{"n":144,"avg":0.082,"win":42,"h1":-0.14,"h2":0.196},"J":{"n":124,"avg":0.161,"win":29,"h1":-0.096,"h2":0.292},"A":{"n":122,"avg":0.234,"win":34,"h1":0.002,"h2":0.356}},"bull|short":{"F":{"n":107,"avg":-0.07,"win":34,"h1":-0.034,"h2":-0.097},"G":{"n":115,"avg":-0.054,"win":31,"h1":-0.034,"h2":-0.069},"B":{"n":115,"avg":-0.022,"win":43,"h1":0.027,"h2":-0.055},"J":{"n":107,"avg":-0.043,"win":34,"h1":-0.017,"h2":-0.062},"A":{"n":100,"avg":-0.025,"win":38,"h1":0.011,"h2":-0.053}}},"XAUUSD":{"bear|long":{"F":{"n":45,"avg":-0.119,"win":31,"h1":-0.058,"h2":-0.255},"G":{"n":48,"avg":-0.023,"win":38,"h1":0.023,"h2":-0.125},"B":{"n":48,"avg":-0.173,"win":33,"h1":-0.121,"h2":-0.275},"J":{"n":45,"avg":-0.099,"win":33,"h1":-0.05,"h2":-0.209},"A":{"n":44,"avg":-0.154,"win":30,"h1":-0.108,"h2":-0.252}},"bear|short":{"F":{"n":39,"avg":0.005,"win":26,"h1":0.25,"h2":-0.228},"G":{"n":47,"avg":0.044,"win":30,"h1":0.198,"h2":-0.117},"B":{"n":44,"avg":0.009,"win":43,"h1":0.088,"h2":-0.077},"J":{"n":39,"avg":0.001,"win":28,"h1":0.225,"h2":-0.211},"A":{"n":37,"avg":0.027,"win":30,"h1":0.261,"h2":-0.195}},"bull|long":{"F":{"n":143,"avg":0.303,"win":39,"h1":-0.005,"h2":0.591},"G":{"n":180,"avg":0.214,"win":41,"h1":0.022,"h2":0.37},"B":{"n":167,"avg":0.159,"win":48,"h1":-0.09,"h2":0.394},"J":{"n":143,"avg":0.281,"win":43,"h1":0.016,"h2":0.527},"A":{"n":143,"avg":0.293,"win":45,"h1":-0.014,"h2":0.586}},"bull|short":{"F":{"n":133,"avg":-0.091,"win":27,"h1":-0.07,"h2":-0.11},"G":{"n":143,"avg":-0.141,"win":27,"h1":-0.114,"h2":-0.167},"B":{"n":141,"avg":-0.085,"win":35,"h1":-0.035,"h2":-0.13},"J":{"n":133,"avg":-0.13,"win":27,"h1":-0.082,"h2":-0.176},"A":{"n":132,"avg":-0.107,"win":27,"h1":-0.095,"h2":-0.118}}}};
function exitLine(sym, env, side) {
  if (!env) return "";
  const k = statKey(sym), ek = `${env.bull ? "bull" : "bear"}|${side === 1 ? "long" : "short"}`;
  const T = (EXIT[k] && EXIT[k][ek]) || ((((window.JSQ_ENV || {}).contract_stats || {})[k] || {})["exit|" + ek]);
  if (!T || T.F.n < 60) return "";
  const keep = T.J.avg >= 0.85 * T.F.avg, UT = (((window.JSQ_ENV || {}).contract_stats || {})[k] || {})["u|" + ek];
  const sg = (v) => UT && UT[v] ? (UT[v].u >= 0 ? "+" : "") + UT[v].u.toFixed(1) + "U" : (T[v].avg >= 0 ? "赚" : "亏") + "止损金额的" + Math.round(Math.abs(T[v].avg) * 100) + "%";
  return `回测（${SAMPLE[k] || (k.startsWith("sym_") ? k.slice(4) + "自己的小时线" : k)}，${env.w50 ? (env.bull ? "比特币50日线上方" : "比特币50日线下方") : env.bull ? "牛市" : "熊市"}${side === 1 ? "做多" : "做空"}${UT ? "，按100U开5倍算" : ""}）：这样出场平均每次 <b>${sg("F")}</b>；2倍先平一半 ${sg("J")}；` +
    `固定2倍全平 ${sg("G")}；1倍就平一半 ${sg("B")}（胜率 ${T.B.win}%，但赚得少）。` +
    (T.A ? `<b>不想算1倍2倍</b>：止损放好不动，等小时线短均线下穿长均线（死叉）再走，平均每次 ${sg("A")}，差不多。` : "") +
    (T.F.avg <= 0 ? "这个方向怎么出场都不赚。" : keep ? "分批影响不大，按习惯来。" : "<b>这类品种分批会少赚不少</b>（钱主要来自少数大行情），能扛住就别分批。");
}
function plan(V, side, tf, at, sym, env, stp) {
  const E0 = at || V.last, dp = V.dp, day = tf === "1d" ? "20日" : V.sess ? "最近7根交易时段小时线" : "24小时", trail = tf === "1d" ? "过去10天" : "过去3天";
  const stop = stp || (side === 1 ? V.L * 0.999 : V.H * 1.001), R = side * (E0 - stop);
  if (!(R > 0) || !isFinite(R)) return `现价已经越过${day}${side === 1 ? "最低" : "最高"}点，按你的规则没法放止损。`;
  const be = E0 + side * R, half = E0 + side * 2 * R;
  PLANNUM = { E0, stop, target: half, side };
  const head = at ? `${side === 1 ? "站上" : "跌破"} ${fmt(at, dp)} 之后${side === 1 ? "做多" : "做空"}参考` : `确认以后按现价（约 ${fmt(E0, dp)}）${side === 1 ? "做多" : "做空"}参考`;
  const sk = statKey(sym), pyr = side === 1 && (sk === "crypto" || (sk === "stock_main" && env && env.bull) || sk === "XAUUSD" || sk === "XAGUSD");
  const ex = pyr ? "" : exitLine(sym, env, side);
  return `${head}：止损 <b>${fmt(stop, dp)}</b>（${day}${side === 1 ? "最低" : "最高"}点外，亏 ${pabs(R / E0, 2)}）。` +
    `<br>① 浮盈到 <b>${fmt(be, dp)}</b>（1倍止损距离）把止损挪到开仓价；` +
    `<br>② 之后止损跟着"${trail}${side === 1 ? "最低" : "最高"}点"${side === 1 ? "往上" : "往下"}挪，只挪不退，碰到就走——<b>不设固定止盈</b>，让大行情自己跑；` +
    (pyr ? `<br>③ 不中途止盈：这类单子用下面的"赚了再加"，所有仓位一起出场。` : `<br>③ 想分批：到 <b>${fmt(half, dp)}</b>（2倍止损距离，赚 ${pabs((half - E0) / E0, 2)}）先平一半，剩下照样跟踪。`) +
    (ex ? `<br><span class="plan-bt">${ex}</span>` : "");
}
// 波动参考：最近20天日波动 σ；80%区间倍数和"碰到概率"表按近5年历史校准（research/vol_range_bt.py，后半段实际罩住76%~82%）
const VOLT = {"ks":[0.25,0.5,0.75,1.0,1.25,1.5,1.75,2.0,2.25,2.5,2.75,3.0,3.25,3.5,3.75,4.0],"g":{"commod":{"k1":1.3,"k5":1.307,"t1":[0.778,0.587,0.427,0.301,0.21,0.146,0.1,0.068,0.046,0.031,0.022,0.015,0.012,0.009,0.007,0.005],"t5":[0.789,0.597,0.439,0.315,0.22,0.149,0.104,0.071,0.05,0.036,0.026,0.018,0.013,0.01,0.008,0.005]},"silver":{"k1":1.269,"k5":1.422,"t1":[0.779,0.594,0.44,0.307,0.216,0.146,0.104,0.07,0.051,0.034,0.026,0.02,0.014,0.012,0.007,0.006],"t5":[0.806,0.607,0.44,0.323,0.232,0.168,0.12,0.085,0.065,0.043,0.031,0.017,0.013,0.008,0.005,0.005]},"gold":{"k1":1.293,"k5":1.39,"t1":[0.763,0.578,0.425,0.295,0.209,0.15,0.103,0.069,0.051,0.035,0.026,0.02,0.015,0.011,0.008,0.007],"t5":[0.782,0.596,0.434,0.316,0.218,0.158,0.12,0.089,0.064,0.046,0.035,0.024,0.019,0.016,0.011,0.009]},"crypto":{"k1":1.229,"k5":1.285,"t1":[0.778,0.571,0.41,0.297,0.215,0.156,0.115,0.086,0.066,0.051,0.04,0.032,0.025,0.021,0.018,0.015],"t5":[0.787,0.59,0.436,0.317,0.23,0.169,0.126,0.098,0.077,0.063,0.05,0.042,0.036,0.03,0.025,0.022]},"stock_other":{"k1":1.254,"k5":1.339,"t1":[0.685,0.525,0.384,0.274,0.192,0.134,0.093,0.065,0.046,0.033,0.024,0.019,0.015,0.011,0.009,0.008],"t5":[0.757,0.575,0.421,0.302,0.214,0.152,0.107,0.075,0.054,0.039,0.029,0.022,0.017,0.013,0.011,0.008]},"stock_nontech":{"k1":1.254,"k5":1.358,"t1":[0.706,0.548,0.403,0.288,0.203,0.143,0.099,0.07,0.049,0.035,0.026,0.02,0.015,0.012,0.009,0.008],"t5":[0.771,0.591,0.436,0.314,0.224,0.157,0.111,0.079,0.055,0.04,0.029,0.022,0.016,0.012,0.01,0.008]},"stock_main":{"k1":1.271,"k5":1.371,"t1":[0.673,0.514,0.376,0.272,0.188,0.131,0.09,0.063,0.045,0.032,0.024,0.018,0.013,0.01,0.008,0.007],"t5":[0.757,0.575,0.425,0.303,0.215,0.148,0.104,0.074,0.054,0.039,0.029,0.02,0.016,0.012,0.009,0.007]}}};
const VOL = {};
let PLANNUM = null;
function volGroup(sym) {
  const k = statKey(sym);
  return k === "XAUUSD" ? "gold" : k === "XAGUSD" ? "silver" : k;
}
async function needVol(sym) {
  if (VOL[sym] && Date.now() - VOL[sym].at < 10 * 60e3) return false;
  const r = await fetch(`${REST}/fapi/v1/klines?symbol=${sym}&interval=1d&limit=45`, { cache: "no-store" });
  if (!r.ok) return false;
  const k = await r.json(); if (!Array.isArray(k)) return false;
  const crypto = U.groupOfSym(sym) === "crypto";
  const c = k.slice(0, -1).filter((x) => { if (crypto) return true; const d = new Date(+x[0]).getUTCDay(); return d !== 0 && d !== 6; }).map((x) => +x[4]).slice(-21);
  if (c.length < 21) return false;
  const lr = c.slice(1).map((x, i) => Math.log(x / c[i])), m = lr.reduce((a, b) => a + b, 0) / lr.length;
  const sd = Math.sqrt(lr.reduce((a, b) => a + (b - m) ** 2, 0) / (lr.length - 1));
  VOL[sym] = { sd, at: Date.now() };
  return true;
}
function touchP(tab, k) {
  const ks = VOLT.ks;
  if (k <= ks[0]) return 1 - (1 - tab[0]) * k / ks[0];
  if (k >= ks[ks.length - 1]) return tab[tab.length - 1];
  const i = ks.findIndex((x) => x >= k), a = ks[i - 1], b = ks[i];
  return tab[i - 1] + (tab[i] - tab[i - 1]) * (k - a) / (b - a);
}
function volText(sym, V) {
  const v = VOL[sym], G = VOLT.g[volGroup(sym)] || VOLT.g.stock_other;
  if (!v) return "";
  const sd = v.sd, P = V.last, dp = V.dp, pc = (x) => Math.round(x * 100) + "%";
  const b1 = [P * Math.exp(-G.k1 * sd), P * Math.exp(G.k1 * sd)], b5 = [P * Math.exp(-G.k5 * sd * Math.sqrt(5)), P * Math.exp(G.k5 * sd * Math.sqrt(5))];
  let t = `<b>波动参考</b>：最近20天平均每天波动 ±${(sd * 100).toFixed(2)}%。明天这个时候 8 成在 <b>${fmt(b1[0], dp)} ~ ${fmt(b1[1], dp)}</b>；5 天后 8 成在 ${fmt(b5[0], dp)} ~ ${fmt(b5[1], dp)}。`;
  if (PLANNUM) {
    const { E0, stop, target } = PLANNUM, ds = Math.abs(Math.log(stop / E0)), dt = Math.abs(Math.log(target / E0));
    const p1 = touchP(G.t1, ds / sd), p5 = touchP(G.t5, ds / sd / Math.sqrt(5)), q1 = touchP(G.t1, dt / sd), q5 = touchP(G.t5, dt / sd / Math.sqrt(5));
    t += `<br>止损离开仓价 ${(Math.abs(stop - E0) / E0 * 100).toFixed(2)}%（${(ds / sd).toFixed(1)} 倍日波动）：光是正常来回，24 小时内被碰到约 <b>${pc(p1)}</b>，5 天内约 ${pc(p5)}。先平一半的位置离开仓价 ${(Math.abs(target - E0) / E0 * 100).toFixed(2)}%：24 小时内碰到约 ${pc(q1)}，5 天内约 ${pc(q5)}。`;
    if (p1 >= 0.45) t += `<b>止损偏近，正常波动就容易扫到</b>，要么等更好的位置，要么仓位减半。`;
    else if (q5 < 0.15) t += `2倍的位置5天内碰到的机会不大，主要靠跟踪止损出场。`;
  }
  return t;
}
// 熊市里 AMD/美光/戴尔 的"回调企稳做多"（research/dip_v2_bt.py）：
// 从5天最高点跌够 2 倍日波动 → 等1小时收盘站上前12小时最高价（止跌企稳）→ 做多；止损这波最低点下方 0.3 倍日波动；目标回到5天高点；1倍浮盈挪保本
const H1 = {};
async function needH1(sym) {
  if (H1[sym] && Date.now() - H1[sym].at < 3 * 60e3) return false;
  const r = await fetch(`${REST}/fapi/v1/klines?symbol=${sym}&interval=1h&limit=600`, { cache: "no-store" });
  if (!r.ok) return false;
  const k = await r.json(); if (!Array.isArray(k) || k.length < 140) return false;
  const rows = k.slice(0, -1).map((x) => ({ t: +x[0], o: +x[1], h: +x[2], l: +x[3], c: +x[4] }));
  const last = +k[k.length - 1][4];
  H1[sym] = { rows, sess: sessRows(rows), at: Date.now(), last, dp: last >= 100 ? 2 : last >= 1 ? 3 : 5 };
  return true;
}
// 美股合约按"交易时段小时线"算（回测用的就是美股交易时段：每天7根，纽约时间9点到16点）
const NYF = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", hour12: false, weekday: "short", month: "numeric", day: "numeric" });
function nyInfo(t) { const p = NYF.formatToParts(new Date(t)); const g = (k) => (p.find((x) => x.type === k) || {}).value; return { hr: +g("hour") % 24, wd: g("weekday"), md: `${g("month")}月${g("day")}日` }; }
function sessRows(rows) { return rows.filter((x) => { const n = nyInfo(x.t); return n.wd !== "Sat" && n.wd !== "Sun" && n.hr >= 9 && n.hr <= 15; }); }
function addTradingDays(t, n) { let d = new Date(t), k = 0; while (k < n) { d = new Date(d.getTime() + 864e5); const w = nyInfo(d.getTime()).wd; if (w !== "Sat" && w !== "Sun") k++; } return nyInfo(d.getTime()).md; }
const maxH = (R, a, b) => { let m = -Infinity; for (let i = Math.max(0, a); i < b; i++) m = Math.max(m, R[i].h); return m; };
const minL = (R, a, b) => { let m = Infinity; for (let i = Math.max(0, a); i < b; i++) m = Math.min(m, R[i].l); return m; };
// 和回测同一套（research/dip_clean_bt.py）：收盘跌到"前35根最高 × e^(−2σ)"以下=跌够，5天高点在这一刻定死；
// 之后35根内收盘站上前4根最高且还在高点下方=企稳进场；止损=跌够以来最低点×e^(−0.3σ)；1R保本；回到5天高点全平；最多10个交易日
function dipEpisode(R, sd) {
  const N = R.length - 1; let t = Math.max(35, N - 140), last = null;
  while (t <= N) {
    const top = maxH(R, t - 35, t);
    if (!(R[t].c <= top * Math.exp(-2 * sd))) { t++; continue; }
    let low = R[t].l, k = -1;
    for (let u = t; u <= Math.min(N, t + 34); u++) { low = Math.min(low, R[u].l); if (u > t && R[u].c > maxH(R, u - 4, u) && R[u].c < top) { k = u; break; } }
    if (k < 0) { if (t + 34 < N) { t += 35; continue; } return { stage: "wait", t, top, low, trig: maxH(R, N - 3, N + 1) }; }
    const E0 = R[k].c, stop = low * Math.exp(-0.3 * sd), Rk = E0 - stop; let st = stop, end = -1, why = "";
    for (let j = k + 1; j <= Math.min(N, k + 70); j++) {
      if (R[j].l <= st) { end = j; why = st >= E0 ? "回到开仓价保本出场" : "打到止损"; break; }
      if (R[j].h >= E0 + Rk) st = Math.max(st, E0);
      if (R[j].h >= top) { end = j; why = "回到5天高点止盈"; break; }
    }
    if (end < 0 && k + 70 <= N) { end = k + 70; why = "拿满10个交易日到期"; }
    const ep = { t, k, top, low, E0, stop, Rk, kt: R[k].t, deadline: addTradingDays(R[k].t, 10) };
    if (end < 0) return Object.assign(ep, { stage: "open", st });
    last = Object.assign(ep, { stage: "done", why, et: R[end].t }); t = end + 1;
  }
  return { stage: "none", last, top: maxH(R, N - 34, N + 1) };
}
function ndxDipped() {
  const us = ((window.JSQ_ENV || {}).us || {}).series || [];
  if (us.length < 22) return false;
  const c = us.slice(-21).map((x) => x.ndx), lr = c.slice(1).map((x, i) => Math.log(x / c[i]));
  const m = lr.reduce((a, b) => a + b, 0) / lr.length, sd = Math.sqrt(lr.reduce((a, b) => a + (b - m) ** 2, 0) / (lr.length - 1));
  const last5 = c.slice(-5), top = Math.max(...last5);
  return Math.log(c[c.length - 1] / top) <= -2 * sd;
}
function ndxUpBefore(t) {   // 企稳那天之前最近一个交易日纳指是不是涨的
  const us = ((window.JSQ_ENV || {}).us || {}).series || [], d = new Date(t).toISOString().slice(0, 10);
  const prev = us.filter((x) => x.d < d); if (prev.length < 2) return null;
  return prev[prev.length - 1].ndx > prev[prev.length - 2].ndx;
}
function dipState(sym, V, mode) {
  const bear = mode !== "bull";
  const X = H1[sym], v = VOL[sym];
  if (!X || !v || X.sess.length < 60) return null;
  const R = X.sess, sd = v.sd, dp = V.dp, ep = dipEpisode(R, sd), last = V.last;
  const pc = (x) => (x * 100).toFixed(1) + "%";
  const head = (bear ? `纳指在熊市，这3只股票只在"大跌之后止跌"时买` : `纳指这几天跌得多，这3只股票等"大跌之后止跌"再买更好`) +
    `。做法：先等它从5天高点跌够一大段（约两天的正常波动），再等它涨回最近半天的最高价上方（说明止跌了）才进。`;
  const mgmt = (e) => `① 止损放 <b>${fmt(e.stop, dp)}</b>（这波最低点 ${fmt(e.low, dp)} 下面一点）；② 涨到 <b>${fmt(e.E0 + e.Rk, dp)}</b> 就把止损挪到开仓价，保证不亏；③ 涨到 <b>${fmt(e.top, dp)}</b>（下跌前的高点）全部平掉；④ 到 <b>${e.deadline}</b> 美股收盘还没到目标，也平掉。`;
  if (ep.stage === "none") {
    const need = ep.top * Math.exp(-2 * sd), lastTxt = ep.last ? `上一波（${nyInfo(ep.last.kt).md}在 ${fmt(ep.last.E0, dp)} 止跌）已经结束：${ep.last.why}。` : "";
    return { lv: need, ldir: -1, tier: 2, short: `等它大跌：跌到 ${fmt(need, dp)} 以下再找买点（现 ${fmt(last, dp)}）`, dir: "先不做（跌得还不够）", cls: "flat", why: head + lastTxt + `最近5天最高 ${fmt(ep.top, dp)}，要跌到 <b>${fmt(need, dp)}</b> 以下才算跌够（现价 ${fmt(last, dp)}）。` };
  }
  if (ep.stage === "wait") return { lv: ep.trig, ldir: 1, tier: 1, short: `跌够了，等止跌：涨回 ${fmt(ep.trig, dp)} 上方就做多`, dir: "等止跌再做多", cls: "warn", why: head + `已经跌够了（从 ${fmt(ep.top, dp)} 跌到最低 ${fmt(ep.low, dp)}），但还没止跌：等美股开盘时段价格涨回 <b>${fmt(ep.trig, dp)}</b> 上方再做多（按1小时K线收盘算）。` };
  const age = R.length - 1 - ep.k, upB = ndxUpBefore(ep.kt), kd = nyInfo(ep.kt).md;
  const holder = `<br><span class="plan-bt">如果你在这一波（${kd}，${fmt(ep.E0, dp)} 附近）已经买了，这样管：${mgmt(ep)}</span>`;
  // 这一轮还没结束（没碰止损、没到目标、没过期限）：晚进也行。回测（research/late_entry_bt.py，5年熊市91次）：
  // 晚1天还能进的74次平均+3.2U、晚2天51次+8.6U、晚3天32次+9.1U、晚5天20次+13.3U；止损沿用这一轮的（已过1倍就是原开仓价），止盈原目标，期限不变
  if (age > 3 && bear && upB !== true && ep.stage === "open" && last > ep.st && last < ep.top) {
    const st2 = ep.st, Rk2 = last - st2;
    PLANNUM = { E0: last, stop: st2, target: ep.top, side: 1 };
    const late = `${kd}在 ${fmt(ep.E0, dp)} 止跌买入的这一轮还没结束`;
    return { tier: 0, late: true, short: `${late}：现在进也行，止损 ${fmt(st2, dp)}，止盈 ${fmt(ep.top, dp)}，最晚 ${ep.deadline}`,
      dir: "可以做多（晚进这一轮）", cls: "up",
      why: head + `${late}（还没碰止损、没到目标、没过期限）。<b>晚进也验证过</b>：5年里熊市这样的买点91次，信号出来以后晚1天还能进的74次平均每次赚3.2U，晚2-5天进的平均赚8-13U（次数越晚越少，20-50次）。止损用这一轮的止损${st2 >= ep.E0 ? "（已经涨过1倍，挪到了原开仓价）" : ""}，止盈和期限不变。`,
      plan: `现在买的做法（现价 ${fmt(last, dp)}，错了亏 ${pc(Rk2 / last)}，到目标赚 ${pc((ep.top - last) / last)}）：` +
        (st2 >= ep.E0 ? `① 止损放 <b>${fmt(st2, dp)}</b>（这一轮的开仓价，这一轮已经涨过1倍止损距离）；` : `① 止损放 <b>${fmt(st2, dp)}</b>（这波最低点 ${fmt(ep.low, dp)} 下面一点）；② 涨到 <b>${fmt(ep.E0 + ep.Rk, dp)}</b> 就把止损挪到 ${fmt(ep.E0, dp)}（这一轮的开仓价）；`) +
        `${st2 >= ep.E0 ? "②" : "③"} 涨到 <b>${fmt(ep.top, dp)}</b>（下跌前的高点）全部平掉；${st2 >= ep.E0 ? "③" : "④"} 到 <b>${ep.deadline}</b> 美股收盘还没到目标，也平掉。<br><span class="plan-bt">晚进的次数不多，轻仓。</span>` };
  }
  if (age > 3) {
    const drop = pc(1 - Math.exp(-2 * sd)), nxt = `这一波到 ${ep.deadline} 前结束（先涨到 ${fmt(ep.top, dp)} 或跌破 ${fmt(ep.st, dp)} 就提前结束），之后从那时的5天高点再跌 ${drop} 左右才算跌够`;
    return { tier: 3, short: `${kd}出过买入信号（${fmt(ep.E0, dp)}），现在不追；${nxt}`, dir: "上一个买点已过，现在不追", cls: "flat",
      why: head + `上一个买入信号出在${kd}（${fmt(ep.E0, dp)}）。回测只算了在信号那一刻买，晚买没验证过，所以现在不追。<b>下一次机会</b>：${nxt}，然后再等止跌。`,
      plan: `现在不新开仓。${holder}` };
  }
  if (bear && upB === true) return { tier: 3, short: "止跌了，但纳指昨天在涨，历史上这种情况是亏的，先不进", dir: "先不进（纳指昨天在涨）", cls: "warn", why: head + `已经止跌，但纳指昨天是涨的：历史上这种时候买，19次平均每次亏14.7U；纳指昨天在跌时买，90次平均每次赚6.2U。所以这次不进。`, plan: `先不进。${holder}` };
  const E0 = last, Rk = E0 - ep.stop;
  if (!(Rk > 0) || !(ep.top > E0)) return { tier: 3, short: "先不做", dir: "先不做", cls: "flat", why: head + "现价已经离开这一轮的范围。" };
  PLANNUM = { E0, stop: ep.stop, target: ep.top, side: 1 };
  const e2 = Object.assign({}, ep, { E0, Rk });
  const plan = `现在买的做法（现价 ${fmt(E0, dp)}，错了亏 ${pc(Rk / E0)}，到目标赚 ${pc((ep.top - E0) / E0)}）：${mgmt(e2)}` +
    (bear ? `<br><span class="plan-bt">历史成绩（熊市里这样买，按100U开5倍）：90次，平均每次赚 6.2U，10次里赚4次。次数不多，所以轻仓。</span>`
      : `<br><span class="plan-bt">历史成绩（牛市里大盘一起跌的时候这样买，按100U开5倍）：130次，平均每次赚 4.7U。只对 AMD/美光/戴尔 这3只有效。</span>`);
  return { tier: 0, short: `止跌了，可以轻仓做多：现价 ${fmt(E0, dp)}，止损放 ${fmt(ep.stop, dp)}（错了亏 ${pc(Rk / E0)}），目标 ${fmt(ep.top, dp)}`, dir: "可以轻仓做多（大跌后止跌了）", cls: "up", why: head + `已经跌够，并且${age === 0 ? "刚刚" : "不久前"}止跌了，买点到了。`, plan };
}
// ---------------------------------------------------------------- 突破信号：和回测 research/contract_bt.py 的 breakout 同一套
// 进场：1小时收盘 突破前L根最高（做空=跌破最低）、EMA20在EMA50上方（做空=下方）、收盘高于L根前的收盘；L=24（美股合约=7根交易时段线）
// 止损：L根最低×0.999；浮盈1倍后止损=max(开仓价, 3L根最低)；小时线EMA反穿或满10天离场；止损距离要在0.4%~8%之间
// 日线（币安1d）：给"技术面"综合分里的"日线方向"用——收盘在50日均线上方且均线比5天前高=+1，下方且更低=−1；股票合约去掉周末
const D1 = {};
async function needD1(sym) {
  if (D1[sym] && Date.now() - D1[sym].at < 30 * 60e3) return;
  const r = await fetch(`${REST}/fapi/v1/klines?symbol=${sym}&interval=1d&limit=130`, { cache: "no-store" }); if (!r.ok) return;
  const k = await r.json(); if (!Array.isArray(k) || k.length < 60) return;
  let rows = k.slice(0, -1).map((x) => ({ t: +x[0], c: +x[4] }));
  if (U.groupOfSym(sym) === "stock") rows = rows.filter((x) => { const w = new Date(x.t).getUTCDay(); return w !== 0 && w !== 6; });
  const tr = rows.map((x, i) => { if (i < 54) return 0; let m = 0, m5 = 0; for (let j = i - 49; j <= i; j++) m += rows[j].c; for (let j = i - 54; j <= i - 5; j++) m5 += rows[j].c; m /= 50; m5 /= 50; return x.c > m && m > m5 ? 1 : x.c < m && m < m5 ? -1 : 0; });
  D1[sym] = { rows, tr, at: Date.now() };
}
function dayTrendAt(sym, t) {   // 用这根小时线所在那天之前最近一个日线的方向（不偷看）
  const d = D1[sym]; if (!d) return 0;
  const day0 = Math.floor(t / 864e5) * 864e5; let v = 0;
  for (let i = d.rows.length - 1; i >= 0; i--) if (d.rows[i].t < day0) { v = d.tr[i]; break; }
  return v;
}
// 技术面综合分（和 research/indicator_bt.py 的"综合分"同一套）：均线±1、MACD柱±1、RSI档位(55~70 +1 / 30~45 −1)、突破前L根高低点±1、日线方向±1
function techScore(sym, R, L, up) {
  const n = R.length, sc = new Array(n), parts = new Array(n);
  let e12 = R[0].c, e26 = R[0].c, sg = 0, u = 0, dn = 0;
  for (let i = 0; i < n; i++) {
    const c = R[i].c;
    e12 += (c - e12) * (2 / 13); e26 += (c - e26) * (2 / 27);
    const macd = e12 - e26; sg = i === 0 ? macd : sg + (macd - sg) * (2 / 10); const hist = macd - sg;
    let band = 0, rsi = NaN;
    if (i >= 1) { const d = c - R[i - 1].c, g = Math.max(d, 0), l = Math.max(-d, 0);
      if (i === 1) { u = g; dn = l; } else { u += (g - u) / 14; dn += (l - dn) / 14; }
      rsi = dn === 0 ? NaN : 100 - 100 / (1 + u / dn);
      band = rsi >= 70 ? 0 : rsi >= 55 ? 1 : rsi > 45 ? 0 : rsi > 30 ? -1 : 0; }
    const bk = i >= L ? (c > maxH(R, i - L, i) ? 1 : c < minL(R, i - L, i) ? -1 : 0) : 0, dt = dayTrendAt(sym, R[i].t);
    parts[i] = { ma: up[i] ? 1 : -1, macd: hist > 0 ? 1 : -1, rsi: band, rsiV: rsi, brk: bk, day: dt };
    sc[i] = parts[i].ma + parts[i].macd + band + bk + dt;
  }
  return { sc, parts };
}
// ---------------------------------------------------------------- 信号引擎：和回测同一套（research/contract_bt.py 出场F；对账 research/parity_check.py）
// kind="brk"：1小时收盘突破前L根最高（做空=跌破最低）、EMA20在EMA50上方（做空=下方）、收盘高于L根前的收盘
// kind="tech"：技术面综合分从<2变成≥2（做空：从>−2变成≤−2）
// L=24（美股合约=7根交易时段线）。止损：L根最低×0.999；浮盈1倍后止损=max(开仓价, 3L根最低)；小时线EMA反穿或满10天离场；止损距离要在0.4%~8%之间
const BJF = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short" });
function inSession() { const n = nyInfo(Date.now()); return n.wd !== "Sat" && n.wd !== "Sun" && n.hr >= 9 && n.hr <= 15; }
function confirmAt(stock) {
  // 币：这根1小时线收盘；股票：美股交易时段（纽约 9:00~15:59 开始的小时线）里的下一根收盘
  let t = Math.floor(Date.now() / 3600e3) * 3600e3;
  for (let k = 0; k < 24 * 8; k++, t += 3600e3) {
    const n = nyInfo(t);
    if (!stock || (n.wd !== "Sat" && n.wd !== "Sun" && n.hr >= 9 && n.hr <= 15)) {
      const c = t + 3600e3, p = BJF.formatToParts(new Date(c)), g = (x) => (p.find((y) => y.type === x) || {}).value;
      const dd = Math.round((new Date(new Date(c).toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" })) - new Date(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" }))) / 864e5);
      const day = dd <= 0 ? (+g("hour") >= 18 ? "今晚" : "今天") : dd === 1 ? (+g("hour") >= 18 ? "明晚" : "明天") : g("weekday");
      return { txt: `${day}${g("hour")}:${g("minute")}`, open: stock && k === 0 };
    }
  }
  return { txt: "下一根", open: false };
}
function sigEngine(sym, side, kind, trace) {
  const X = H1[sym]; if (!X) return null;
  const stock = U.groupOfSym(sym) === "stock", R = stock ? X.sess : X.rows, L = stock ? 7 : 24, N = R.length - 1;
  if (N < 90) return null;
  const up = []; let e20 = R[0].c, e50 = R[0].c;
  for (let i = 0; i <= N; i++) { e20 += (R[i].c - e20) * (2 / 21); e50 += (R[i].c - e50) * (2 / 51); up.push(e20 > e50); }
  let sig, TS = null;
  if (kind === "tech") { if (!D1[sym]) return null; TS = techScore(sym, R, L, up); const sc = TS.sc; sig = (i) => i >= 1 && (side === 1 ? sc[i] >= 2 && sc[i - 1] < 2 : sc[i] <= -2 && sc[i - 1] > -2); }
  else sig = (i) => side === 1 ? (up[i] && R[i].c > maxH(R, i - L, i) && R[i].c > R[i - L].c) : (!up[i] && R[i].c < minL(R, i - L, i) && R[i].c < R[i - L].c);
  const last = X.last, win = stock ? "最近7根交易时段小时线" : "24小时";
  let i = 60, open = null;
  while (i <= N) {
    if (!sig(i)) { i++; continue; }
    const E = R[i].c, stop0 = side === 1 ? minL(R, i - L + 1, i + 1) * 0.999 : maxH(R, i - L + 1, i + 1) * 1.001, Rk = side * (E - stop0);
    if (!(Rk >= 0.004 * E && Rk <= 0.08 * E)) { i++; continue; }
    let st = stop0, armed = false, mfe = 0, end = -1, px = NaN, why = "";
    for (let j = i + 1; j <= N; j++) {
      const adv = side === 1 ? R[j].l : R[j].h, fav = side === 1 ? R[j].h : R[j].l;
      if (side * (adv - st) <= 0) { end = j; const op = R[j].o != null ? R[j].o : R[j - 1].c; px = side * (op - st) > 0 ? st : op; why = !armed ? "止损" : side * (st - E) <= E * 1e-9 ? "保本出场" : "跟踪止盈"; break; }
      mfe = Math.max(mfe, side * (fav - E) / Rk); if (mfe >= 1) armed = true;
      if (armed) { const tr = side === 1 ? minL(R, j - 3 * L + 1, j + 1) * 0.999 : maxH(R, j - 3 * L + 1, j + 1) * 1.001; st = side === 1 ? Math.max(st, E, tr) : Math.min(st, E, tr); }
      if ((side === 1 ? (!up[j] && up[j - 1]) : (up[j] && !up[j - 1])) || j - i >= 10 * (stock ? 7 : 24)) { end = j; px = R[j].c; why = j - i >= 10 * (stock ? 7 : 24) ? "满10天" : "小时线趋势反转"; break; }
    }
    if (trace) trace.push({ t: R[i].t, E, stop: stop0, end: end < 0 ? null : R[end].t, px, why, st, armed, Rk });
    if (end < 0) { open = { i, E, stop0, Rk, st, armed, age: N - i, t: R[i].t }; break; }
    i = end + 1;
  }
  const baseOut = { kind, side, last, dp: X.dp, win, stock, score: TS ? TS.sc[N] : null, parts: TS ? TS.parts[N] : null };
  if (open && side * (last - open.st) > 0) {
    const fresh = open.age <= 2 && side * (last - open.E) <= 0.5 * open.Rk;
    return Object.assign(baseOut, { stage: fresh ? "fresh" : "open" }, open);
  }
  const stopIf = side === 1 ? minL(R, N - L + 2, N + 1) * 0.999 : maxH(R, N - L + 2, N + 1) * 1.001;
  if (kind === "tech") return Object.assign(baseOut, { stage: "flat", stopIf, near: side === 1 ? TS.sc[N] === 1 : TS.sc[N] === -1 });
  // 还没有信号：下一根小时线收盘要越过的价位
  const level = side === 1 ? maxH(R, N - L + 1, N + 1) : minL(R, N - L + 1, N + 1);
  let atr = 0; for (let j = N - 23; j <= N; j++) atr += Math.max(R[j].h - R[j].l, Math.abs(R[j].h - R[j - 1].c), Math.abs(R[j].l - R[j - 1].c)); atr /= 24;
  const lp = PX.m[sym] && Date.now() - PX.at < 180e3 ? PX.m[sym] : last;
  const dist = side * (level - lp), crossed = dist < 0;
  return Object.assign(baseOut, { stage: "flat", level, dist, lp, atr, crossed, when: crossed ? confirmAt(stock) : null, near: dist <= atr, trendOK: side === 1 ? up[N] : !up[N], stopIf });
}
const brk = (sym, side, trace) => sigEngine(sym, side, "brk", trace);
// "技术面翻多"当进场信号：只给回测里前后两段都赚的组合——AMD/美光/戴尔（纳指牛市做多）、7个主流币（比特币在50日线上方做多）
const techOK = (sym, env, side) => !!env && env.bull && side === 1 && ["stock_main", "crypto"].includes(statKey(sym));
window.JSQ_BRK = (sym, side, kind) => { const tr = []; sigEngine(sym, side, kind || "brk", tr); return tr; };
window.JSQ_NEEDD1 = needD1;
const OKG = (x) => x === "edge" || x === "unstable";
const SCANERR = {}, D1seen = {};
// 一个品种现在在哪一步：tier 0 可以做 / 1 快到了 / 2 等信号 / 3 已经在走或暂不进 / 4 不做 / 9 载入中
const agoTxt = (b) => { const a = b.age || 0; if (b.stock) return a < 7 ? "今天" : Math.round(a / 7) + "个交易日前"; return a < 1 ? "刚刚" : a < 24 ? a + "小时前" : Math.round(a / 24) + "天前"; };
function symState(sym) {
  const env = envFor(sym), X = H1[sym], name = U.names[sym] || sym.replace(/USDT$/, ""), base = { sym, name };
  if (SCANERR[sym] && !X) return Object.assign(base, { tier: 9, short: "行情没取到，稍后再试" });
  if (!env || !X) return Object.assign(base, { tier: 9, short: "载入中…" });
  const key = statKey(sym), f = (x) => fmt(x, X.dp), envW = env.lbl || (env.w50 ? (env.bull ? "比特币在50日线上方" : "比特币在50日线下方") : env.bull ? "牛市" : "熊市");
  if (key === "stock_main" && (!env.bull || ndxDipped())) {
    const d = VOL[sym] ? dipState(sym, { dp: X.dp, last: X.last }, env.bull ? "bull" : "bear") : null;
    if (!env.bull) return d ? Object.assign(base, { tier: d.tier, short: d.short, kind: "dip", lv: d.lv, ldir: d.ldir }) : Object.assign(base, { tier: 9, short: "载入中…" });
    if (d && d.tier <= 1) return Object.assign(base, { tier: d.tier, short: d.short, kind: "dip", lv: d.lv, ldir: d.ldir });
  }
  const stL = statFor(sym, env.bull, "long"), stS = statFor(sym, env.bull, "short"), gL = grade(stL), gS = grade(stS);
  const side = OKG(gL) ? 1 : OKG(gS) ? -1 : 0;
  if (!side) {
    const why = gL === "none" && gS === "none" ? "还没验证过，不做" : (gL === "few" || gS === "few") && !["lose", "flat"].includes(gL) ? `现在是${envW}，历史上这种情况太少，算不准` : `现在是${envW}，历史上这时候做多做空都不赚`;
    const dm = DMA[sym], lv = dm && (env.m50 ? dm.ma50 : dm.ma200), ln = env.m50 ? "50日线" : "200日线", w200 = dm && U.groupOfSym(sym) === "metal" && !env.bull && isFinite(lv) ? `；要等收盘站上${ln} ${f(lv)}（还差 ${pabs(lv / X.last - 1)}）才开始找做多` : "";
    return Object.assign(base, { tier: 4, short: why + w200 });
  }
  const b = brk(sym, side); if (!b) return Object.assign(base, { tier: 9, short: "载入中…" });
  const w = side === 1 ? "做多" : "做空", brkW = side === 1 ? "突破" : "跌破", bar = b.stock ? "交易时段1小时收盘" : "1小时收盘", light = (side === 1 ? gL : gS) === "unstable" ? "（轻仓）" : "";
  if (b.stage === "fresh") return Object.assign(base, { tier: 0, side, b, short: `现在可以${w}${light}：现价 ${f(b.last)}，止损放 ${f(b.stop0)}（错了亏 ${pabs(side * (b.last - b.stop0) / b.last)}）` });
  const tk = techOK(sym, env, side) ? sigEngine(sym, 1, "tech") : null;      // 第二种进场：技术面翻多
  if (tk && tk.stage === "fresh") return Object.assign(base, { tier: 0, side, b: tk, short: `现在可以做多（几个指标刚一起转多）：现价 ${f(tk.last)}，止损放 ${f(tk.stop0)}（错了亏 ${pabs((tk.last - tk.stop0) / tk.last)}）` });
  const alt = tk && tk.stage === "flat" ? `；或者等几个指标一起转多` : "";
  if (b.stage === "open") return Object.assign(base, { tier: alt ? 2 : 3, side, b, short: `${agoTxt(b)}出过${w}信号（${brkW} ${f(b.E)}），现在不追；${side === 1 ? "跌回" : "涨回"} ${f(b.st)} ${side === 1 ? "以下" : "以上"}这一波才算结束，之后等下一次${brkW}` + alt });
  const more = b.trendOK ? "" : `，并且短期走势要先转${side === 1 ? "强" : "弱"}`;
  if (b.crossed) {
    const pos = side === 1 ? "上方" : "下方", closed = b.stock && !b.when.open && !inSession();
    return Object.assign(base, { tier: 1, side, b, short: `现价 ${f(b.lp)} 已经在 ${f(b.level)} ${pos}，${closed ? "但美股休市中；" : ""}${b.when.txt}那根1小时线收盘还在 ${f(b.level)} ${pos}，就是${w}信号${more}` + alt });
  }
  return Object.assign(base, { tier: b.near || (tk && tk.stage === "flat" && tk.near) ? 1 : 2, side, b, short: `${side === 1 ? "涨过" : "跌破"} ${f(b.level)} 再${w}${light}，还差 ${pabs(b.dist / b.lp)}${more}` + alt });
}
const SCAN = { busy: false, at: 0 };
function scanSyms() {
  const out = ["XAUUSDT", "XAGUSDT"].concat(TESTED_CRYPTO, TESTED_MAIN);
  let fv = []; try { fv = typeof U.favs === "function" ? U.favs() : (U.favs || []); } catch (e) {}
  for (const s of fv) if (!out.includes(s)) out.push(s);
  return out;
}
async function scanAll(force) {
  if (SCAN.busy || (!force && Date.now() - SCAN.at < 4 * 60e3)) return;
  SCAN.busy = true;
  const syms = scanSyms();
  try {
    await Promise.all([needDMA("BTCUSDT"), needDMA("XAUUSDT"), needDMA("XAGUSDT")].map((p) => Promise.resolve(p).catch(() => {})));
    for (let i = 0; i < syms.length; i += 4) {
      await Promise.all(syms.slice(i, i + 4).map(async (s) => {
        try {
          const g = U.groupOfSym(s);
          if (g === "metal" && !["XAUUSDT", "XAGUSDT"].includes(s)) await Promise.resolve(needDMA(s)).catch(() => {});
          await needH1(s); if (!H1[s]) SCANERR[s] = true;
          if (TESTED_MAIN.includes(s)) await needVol(s);
          if (TESTED_MAIN.includes(s) || TESTED_CRYPTO.includes(s)) await needD1(s);
        } catch (e) { SCANERR[s] = true; }
      }));
      renderScan();
    }
    SCAN.at = Date.now();
  } finally { SCAN.busy = false; renderScan(); }
}
function laneATR(sym) {
  const X = H1[sym]; if (!X) return NaN;
  const R = U.groupOfSym(sym) === "stock" && X.sess.length > 30 ? X.sess : X.rows, N = R.length - 1; if (N < 25) return NaN;
  let a = 0; for (let j = N - 23; j <= N; j++) a += Math.max(R[j].h - R[j].l, Math.abs(R[j].h - R[j - 1].c), Math.abs(R[j].l - R[j - 1].c));
  return a / 24;
}
// 一行信号跑道：右边那根线是信号线，点越靠右越近；左端 = 离信号还有8倍"1小时平均波动"以上
function sigLane(r) {
  const X = H1[r.sym], LINE = 0.84, held = numv(loadPos(r.sym).E) > 0, hp = loadPos(r.sym);
  const note = held ? `已有${+hp.side === -1 ? "空" : "多"}单` : "";
  if (r.tier === 9 || !X) return { key: "s-" + r.sym, sym: r.sym, name: r.name, small: "载入中", x: 0.02, dot: "off", v: "—", tier: 9 };
  const f = (x) => fmt(x, X.dp), side = r.side || (r.kind === "dip" ? 1 : 0);
  const ticks = [[LINE * 0.25, "", "f"], [LINE * 0.5, "", "f"], [LINE * 0.75, "", "f"], [LINE, "", "sig"]];
  const zones = [[LINE * 7 / 8, LINE, "near"], [LINE, 1, side === -1 ? "dn" : "up"]];
  const pos = (n) => LINE - Math.min(1, Math.max(0, n) / 8) * LINE;
  const o = { key: "s-" + r.sym, sym: r.sym, name: r.name, ticks, zones, note, tier: r.tier, small: side === -1 ? "↓ 做空" : "↑ 做多" };
  if (r.tier === 0) return Object.assign(o, { x: LINE + 0.05, dot: "go " + (side === -1 ? "dn" : "up"), v: "现在可以做", vs: side === -1 ? "做空" : "做多", cls: "go" });
  if (r.kind === "dip" && isFinite(r.lv)) {
    const d = r.ldir * (r.lv - X.last), n = d / laneATR(r.sym);
    return Object.assign(o, { small: r.ldir === 1 ? "↑ 止跌做多" : "等大跌", x: pos(n), dot: n <= 1 ? "near" : "", v: `${r.ldir === 1 ? "涨回" : "跌到"} ${f(r.lv)}`, vs: `差 ${pabs(d / X.last)}` });
  }
  const b = r.b;
  if (r.kind === "dip" || !b) return Object.assign(o, { x: 0.95, dot: "past", v: "出过信号", vs: "现在不追", cls: "past" });
  if (b.stage === "open") return Object.assign(o, { x: 0.95, dot: "past", v: "信号进行中", vs: "现在不追", cls: "past" });
  if (b.crossed) return Object.assign(o, { x: LINE + 0.07, dot: "cross " + (side === -1 ? "dn" : "up"), v: `已${side === -1 ? "跌破" : "涨过"} ${f(b.level)}`, vs: `等${b.when.txt}收盘`, cls: "cross" });
  const n = b.dist / (b.atr || laneATR(r.sym));
  return Object.assign(o, { x: pos(n), dot: n <= 1 ? "near" : "", v: `${side === -1 ? "跌破" : "涨过"} ${f(b.level)}`, vs: `差 ${pabs(b.dist / b.lp)}`, note: note || (b.trendOK ? "" : `还要短期走势先转${side === -1 ? "弱" : "强"}`) });
}
let SCANROWS = [], SIGL = [];
function renderSigLanes(rows) {
  const box = $("sigLanes"); if (!box) return;
  SIGL = rows.filter((r) => r.tier !== 4 && r.kind !== "ep").map(sigLane).filter(Boolean);
  SIGL.sort((a, b) => (a.tier === 9) - (b.tier === 9) || b.x - a.x);
  const no = rows.filter((r) => r.tier === 4).map((r) => r.name);
  box.innerHTML = SIGL.map(laneHTML).join("") + (no.length ? `<p class="ln-no">不做：${esc(no.join("、"))}</p>` : "");
  slideLanes(box);
}
function renderTodo() {
  const el = $("todoList"); if (!el) return;
  const it = [], HELD = {}; for (const p of allPos()) { const g = U.groupOfSym(p.sym); HELD[g] = (HELD[g] || 0) + 1; }
  const CAPS = { crypto: 4, stock: 3, metal: 2 }, GNM = { crypto: "币", stock: "股票", metal: "金银" };
  for (const [sym, p] of Object.entries(POSPLAN)) if (p.act && (p.cls !== "flat" || /平掉/.test(p.act)) && !/不动/.test(p.act))
    it.push({ k: p.cls === "bad" ? 0 : /平掉/.test(p.act) ? 1 : 2, sym, c: p.cls === "bad" ? "bad" : p.cls === "ok" ? "ok" : "warn", h: `持仓 · ${p.name} ${p.side === 1 ? "多单" : "空单"}`, b: p.act, pos: true });
  for (const r of SCANROWS) {
    if (r.tier === 0) {
      const held = numv(loadPos(r.sym).E) > 0, g = U.groupOfSym(r.sym), full = !held && (HELD[g] || 0) >= (CAPS[g] || 99);
      it.push({ k: held || full ? 4 : 3, sym: r.sym, c: held || full ? "wait" : "go", h: `${held ? "已有仓位" : full ? "到上限了" : "可以做"} · ${r.name}`, b: r.short + (held ? "（已经有仓位，不重复开）" : full ? `（${GNM[g]}已经拿了 ${HELD[g]} 个，先不开）` : "") });
    } else if (r.tier === 1 && r.b && r.b.crossed) it.push({ k: 5, sym: r.sym, c: "wait", h: `等收盘确认 · ${r.name}`, b: r.short });
  }
  it.sort((a, b) => a.k - b.k);
  const head = $("scanHead");
  if (!it.length) {
    const nx = SIGL.filter((l) => l.tier && l.tier <= 2 && l.cls !== "past" && l.x > 0.02).sort((a, b) => b.x - a.x)[0];
    el.innerHTML = `<div class="todo-none"><b>现在没有要做的</b>${nx ? `<span>离得最近的：<b>${esc(nx.name)}</b> ${nx.v}（${nx.vs}）。不到就不动，手上的单按"我的持仓"里的计划管。</span>` : "<span>等扫描完…</span>"}</div>`;
    if (head) head.textContent = SCANROWS.length ? "现在没有" : "正在扫描…";
    return;
  }
  if (head) head.textContent = `${it.length} 件`;
  el.innerHTML = it.map((x) => `<button type="button" class="todo-i ${x.c}" data-sym="${esc(x.sym)}"${x.pos ? ' data-pos="1"' : ""}><span class="ti-h">${esc(x.h)}</span><b>${x.b}</b></button>`).join("");
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => goSym(b.dataset.sym, b.dataset.pos ? "posBox" : "card")));
}
function renderScan() {
  const el = $("scanList"); if (!el) return;
  const rows = scanSyms().map(symState), E = window.JSQ_ENV || {}, u = usNow();
  // 美股放量跳空：只有纳指牛市、今天是"第二天开盘前"才算能做
  if (u && u.bull && Array.isArray(E.ep)) for (const e of E.ep) if (e.days === 0 && e.last >= e.low) rows.push({ sym: e.t + "USDT", name: U.names[e.t + "USDT"] || e.t, tier: 0, short: `放量跳空：下一个美股开盘做多，止损 ${e.low}，拿20个交易日`, kind: "ep" });
  const HELD = {}; for (const p of allPos()) { const g = U.groupOfSym(p.sym); HELD[g] = (HELD[g] || 0) + 1; }
  const CAPS = { crypto: 4, stock: 3, metal: 2 }, GNM = { crypto: "币", stock: "股票", metal: "金银" };
  const G = [["现在可以做", 0], ["快到了，盯着", 1], ["还在等", 2], ["信号已经出过，现在不追", 3], ["不做", 4], ["载入中", 9]];
  let html = "";
  for (const [title, t] of G) {
    const xs = rows.filter((r) => r.tier === t); if (!xs.length) continue;
    const body = xs.map((r) => {
      const hp = loadPos(r.sym), held = numv(hp.E) > 0, gq = U.groupOfSym(r.sym), full = !held && t <= 2 && (HELD[gq] || 0) >= (CAPS[gq] || 99);
      const tag = held ? `<i class="has">已有${+hp.side === -1 ? "空" : "多"}单</i>` : "";
      const extra = held && t <= 1 ? `（已经有仓位：按上面"我的持仓"管，不重复开）` : full ? `（${GNM[gq]}已经拿了 ${HELD[gq]} 个，到上限了，这个先不开）` : "";
      return `<button type="button" class="scan-row t${t}" data-sym="${esc(r.sym)}"><b>${esc(r.name)}${tag}</b><span>${esc(r.short)}${extra}</span></button>`;
    }).join("");
    html += t === 4 ? `<details class="scan-more"><summary class="scan-g">${title}（${xs.length}）：${esc(xs.map((r) => r.name).join("、"))}</summary>${body}</details>` : `<div class="scan-g t${t}">${title}（${xs.length}）</div>` + body;
  }
  const n0 = rows.filter((r) => r.tier === 0).length, n1 = rows.filter((r) => r.tier === 1).length, loading = rows.some((r) => r.tier === 9 && !SCANERR[r.sym]);
  void n0; void n1; void loading;
  el.innerHTML = html;
  SCANROWS = rows; renderSigLanes(rows); renderTodo(); renderPaper();
  const rest = U.all.length - new Set(rows.map((r) => r.sym)).size;
  $("scanNote").innerHTML = `这里只列验证过能赚钱的品种（黄金、白银、7个主流币、AMD/美光/戴尔）和你收藏的，其余 ${rest} 只都<b>不做</b>。价位按1小时K线收盘算。点一行看具体怎么做。` + (SCAN.at ? `（${new Date(SCAN.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} 更新，每5分钟刷新）` : "");
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => goSym(b.dataset.sym)));
}
// ---------------------------------------------------------------- 规则冻结后的自动记账（pages/ledger.py 每天生成 ledger.json）
async function renderLedger() {
  const el = $("ledgerBox"); if (!el) return;
  let L = null; try { const r = await fetch("ledger.json?t=" + Math.floor(Date.now() / 6e5), { cache: "no-store" }); if (r.ok) L = await r.json(); } catch (e) {}
  const Q = ((window.JSQ_ENV || {}).bt_quarters || {}).rows || [], sg = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(Math.abs(x) >= 100 ? 0 : 1)}U`;
  let h = "";
  if (!L) h += `<p class="note">账本还没生成，下次数据更新后出现。</p>`;
  else {
    h += `<p class="led-sum">规则从 <b>${esc(L.frozen)}</b> 起定下来不再改，之后每出一个信号自动记一笔（不用真钱，每笔按100U开5倍、已扣手续费）。` +
      (L.n ? `到现在 <b>${L.n}</b> 笔，已平 ${L.closed} 笔（赚 ${L.win} 笔），已平的合计 <b>${sg(L.closed_u)}</b>，连没平的一起算 ${sg(L.total_u)}。` : `到现在还没有信号。`) +
      ` 数据到 ${esc(String(L.data_to).slice(0, 16))}（UTC，比实时晚一天左右）。</p>`;
    if (L.by_rule && L.by_rule.length) h += `<p class="note">按做法：` + L.by_rule.map((x) => `${esc(x.rule)} ${x.n}笔 ${sg(x.u)}`).join("；") + `</p>`;
    if (L.trades && L.trades.length) h += `<div class="tablewrap"><table><thead><tr><th>品种</th><th>做法</th><th>进场（UTC）</th><th>进场价</th><th>止损</th><th>状态</th><th>盈亏</th></tr></thead><tbody>` +
      L.trades.slice(0, 40).map((t) => `<tr><td>${esc(t.name)}</td><td>${esc(t.rule)}${esc(t.dir)}</td><td>${esc(t.t_in.slice(5, 16).replace("T", " "))}</td><td>${t.px_in}</td><td>${t.stop}</td><td>${esc(t.status)}${t.why ? "·" + esc(t.why) : ""}</td><td>${sg(t.u)}</td></tr>`).join("") + `</tbody></table></div>`;
  }
  if (Q.length) {
    const neg = Q.filter((x) => x.u < 0).length, worst = Math.min(...Q.map((x) => x.u)), last = Q.slice(-8);
    h += `<p class="led-sum" style="margin-top:10px"><b>心里要有数：亏钱的季度是常有的。</b>回测里同样的规则（12个品种每个信号都做），${Q.length} 个季度里有 ${neg} 个季度是亏的，最差一个季度亏 ${Math.abs(worst)}U。最近8个季度：` +
      last.map((x) => `${x.q} ${sg(x.u)}`).join("，") + `。</p>`;
  }
  el.innerHTML = h;
}
// ---------------------------------------------------------------- 持仓总览（所有填过的仓位）
const PX = { at: 0, m: {} };
async function needPrices() {
  if (Date.now() - PX.at < 30e3) return;
  const r = await fetch(`${REST}/fapi/v1/ticker/price`, { cache: "no-store" }); if (!r.ok) return;
  const a = await r.json(); if (!Array.isArray(a)) return;
  PX.m = {}; for (const x of a) PX.m[x.symbol] = +x.price; PX.at = Date.now();
}
function allPos() {
  const out = [];
  try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith("jsq.pos.")) { const o = JSON.parse(localStorage.getItem(k) || "{}"); if (o && numv(o.E) > 0) out.push({ sym: k.slice(8), side: +o.side || 1, E: numv(o.E), S: numv(o.S), N: numv(o.N), Q: numv(o.Q), liq: numv(o.liq), bn: o.src === "bn", avgDn: +o.avgDn || 0, addUp: +o.addUp || 0 }); } } } catch (e) {}
  return out;
}
// ================================================================ 模拟仓：信号一出就按规则自动开、自动平（每笔100U开5倍）
// 正式记录在 gh-pages 的 ledger.json（每天数据更新后由 pages/ledger.py 记账，按当时的牛熊）；
// 页面在它上面做两件事：① 用实时小时线把还没平的单子往前推（止损挪了、被打掉了马上看到）；② 记账数据之后新出的信号先记成"今天的"，第二天正式入账。
const PAPER = { L: null, at: 0, book: null };
const PNOT = 500;
const paperU = (side, E, px) => PNOT * (side * (px - E) / E - 0.001);
async function loadLedger(force) {
  if (!force && PAPER.L && Date.now() - PAPER.at < 600e3) return PAPER.L;
  try { const r = await fetch("ledger.json", { cache: "no-store" }); if (r.ok) { PAPER.L = await r.json(); PAPER.at = Date.now(); } } catch (e) {}
  return PAPER.L;
}
function paperRules(sym) {
  const env = envFor(sym); if (!env) return [];
  if (statKey(sym) === "stock_main") return env.bull ? [{ side: 1, kind: "brk", rule: "突破" }, { side: 1, kind: "tech", rule: "技术面翻多" }] : [];
  const gL = grade(statFor(sym, env.bull, "long")), gS = grade(statFor(sym, env.bull, "short")), out = [];
  if (OKG(gL)) { out.push({ side: 1, kind: "brk", rule: "突破" }); if (techOK(sym, env, 1)) out.push({ side: 1, kind: "tech", rule: "技术面翻多" }); }
  else if (OKG(gS)) out.push({ side: -1, kind: "brk", rule: "跌破" });
  return out;
}
function buildPaper() {
  const L = PAPER.L; if (!L) return null;
  const frozen = Date.parse((L.frozen || "2026-11-10") + "T00:00:00Z"), dataTo = Date.parse(String(L.data_to || "").replace(" ", "T")) || 0;
  const TR = {}, trace = (sym, side, kind) => { const k = sym + side + kind; if (!(k in TR)) { const t = []; try { if (H1[sym]) sigEngine(sym, side, kind, t); } catch (e) {} TR[k] = H1[sym] ? t : null; } return TR[k]; };
  const live = (sym) => (PX.m[sym] && Date.now() - PX.at < 180e3 ? PX.m[sym] : (H1[sym] || {}).last);
  const book = [];
  const fromTrace = (x, base) => {
    const side = base.side, last = live(base.sym);
    if (x.end) return Object.assign(base, { status: "已平", px_out: x.px, why: x.why, t_out: x.end, u: paperU(side, base.E, x.px) });
    return Object.assign(base, { status: "持仓中", st: x.st, armed: x.armed, Rk: x.Rk, last, u: isFinite(last) ? paperU(side, base.E, last) : base.u });
  };
  for (const t of L.trades || []) {
    const side = t.dir === "空" ? -1 : 1, kind = t.rule === "技术面翻多" ? "tech" : (t.rule === "突破" || t.rule === "跌破") ? "brk" : null;
    const base = { sym: t.sym, name: t.name || (U.names[t.sym] || t.sym), rule: t.rule, side, E: +t.px_in, stop0: +t.stop, t_in: Date.parse(t.t_in), u: +t.u, src: "ledger" };
    const tr = kind ? trace(t.sym, side, kind) : null, x = tr && tr.find((y) => Math.abs(y.t - base.t_in) <= 3600e3);
    if (x) { book.push(fromTrace(x, base)); continue; }
    // 实时推不了的（回调企稳、放量跳空、小时线不在页面上）：已平照记账；持仓中的用现价算浮动盈亏
    if (t.status === "已平") book.push(Object.assign(base, { status: "已平", px_out: +t.px_out, why: t.why, t_out: Date.parse(t.t_out) }));
    else {
      const last = live(t.sym), st0 = +t.stop;
      if (isFinite(last) && last > 0 && isFinite(st0) && side * (last - st0) <= 0) book.push(Object.assign(base, { status: "已平", px_out: st0, why: "止损（按现价判断，明早记账确认）", t_out: Date.now(), u: paperU(side, base.E, st0) }));
      else book.push(Object.assign(base, { status: "持仓中", st: st0, last, u: isFinite(last) && last > 0 ? paperU(side, base.E, last) : +t.u }));
    }
  }
  // 记账数据之后新出的信号（按现在的牛熊），先记成"今天的"
  for (const sym of scanSyms()) for (const r of paperRules(sym)) {
    const tr = trace(sym, r.side, r.kind); if (!tr) continue;
    for (const x of tr) {
      if (x.t < frozen || x.t <= dataTo) continue;
      if (book.some((b) => b.sym === sym && Math.abs(b.t_in - x.t) <= 3600e3 && b.side === r.side)) continue;
      book.push(fromTrace(x, { sym, name: U.names[sym] || sym.replace(/USDT$/, ""), rule: r.rule, side: r.side, E: x.E, stop0: x.stop, t_in: x.t, prov: true }));
    }
  }
  book.sort((a, b) => b.t_in - a.t_in);
  const cl = book.filter((b) => b.status === "已平"), op = book.filter((b) => b.status === "持仓中");
  const sum = (a) => a.reduce((x, b) => x + (+b.u || 0), 0);
  PAPER.book = { book, cl, op, closedU: sum(cl), openU: sum(op), win: cl.filter((b) => b.u > 0).length, frozen: L.frozen, dataTo: L.data_to };
  window.JSQ_PAPER = PAPER.book; document.dispatchEvent(new CustomEvent("jsq-paper"));
  return PAPER.book;
}
const dts = (ms) => { const d = new Date(ms + 8 * 3600e3); return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${String(d.getUTCHours()).padStart(2, "0")}:00`; };
async function renderPaper() {
  const box = $("paperOpen"); if (!box) return;
  await loadLedger(false);
  const B = buildPaper();
  if (!B) { box.innerHTML = `<p class="note">模拟仓的记账没载入。</p>`; return; }
  const u1 = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(1)}U`;
  $("paperSum").innerHTML = `<div><small>已平合计</small><b class="${B.closedU >= 0 ? "g" : "r"}">${u1(B.closedU)}</b><p>${B.cl.length} 笔，赚的 ${B.win} 笔</p></div>` +
    `<div><small>持仓中浮动</small><b class="${B.openU >= 0 ? "g" : "r"}">${u1(B.openU)}</b><p>${B.op.length} 笔还没平</p></div>`;
  const sub = $("paperSub"); if (sub) sub.textContent = `${(B.frozen || "").slice(5).replace("-", "月")}日起，信号一出就按规则开，每笔100U开5倍`;
  const rp = PAPER.L && PAPER.L.replay30, rpe = $("paperReplay");
  if (rpe) rpe.innerHTML = rp && rp.n ? `参照：把最近30天（${rp.start.slice(5).replace("-", "月")}日起）照同一套规则回放一遍，${rp.n} 笔，已平 ${rp.closed} 笔合计 <b class="${rp.closed_u >= 0 ? "g" : "r"}">${u1(rp.closed_u)}</b>（赚的 ${rp.win} 笔），还没平的浮动 ${u1(rp.open_u)}。` +
    `这一段大部分在规则定下以前，不算验证，只说明最近行情对这套规则不友好；验证页的"模拟账户"里，中途回撤几百到一千多U是正常的。` : "";
  box.innerHTML = B.op.length ? B.op.map((b) => {
    const X = H1[b.sym], dp = X ? X.dp : (b.E >= 100 ? 2 : 4), f = (x) => fmt(x, dp), up = b.side === 1;
    const q = { E: b.E, last: b.last, side: b.side, stop: b.st, target: NaN, one: b.Rk ? b.E + b.side * b.Rk : NaN, tgtLb: "" };
    const stW = !isFinite(b.st) ? "" : b.armed ? (b.side * (b.st - b.E) > 1e-9 * b.E ? `止损已跟到 ${f(b.st)}（锁住 ${u1(paperU(b.side, b.E, b.st))}）` : `止损已挪到开仓价 ${f(b.st)}`) : `止损 ${f(b.st)}${isFinite(q.one) ? `，到 ${f(q.one)} 挪保本` : ""}`;
    return `<button type="button" class="scan-row paper" data-sym="${esc(b.sym)}"><b>${esc(b.name)} ${up ? "多" : "空"}<i class="pr">${esc(b.rule)}${b.prov ? " · 今天的" : ""}</i></b><span>${dts(b.t_in)} 开在 ${f(b.E)} → 现 ${isFinite(b.last) ? f(b.last) : "—"}｜<b class="${b.u >= 0 ? "g" : "r"}">${u1(b.u)}</b><br>${stW}` +
      `${isFinite(b.last) && isFinite(b.st) ? railHTML("p-" + b.sym + b.t_in, q, f) : ""}</span></button>`;
  }).join("") : `<p class="note">现在没有持仓中的模拟单。</p>`;
  const cbox = $("paperClosed");
  if (cbox) cbox.innerHTML = B.cl.length ? `<table class="shadow-t"><thead><tr><th>平掉的</th><th>怎么平的</th><th class="n">结果</th></tr></thead><tbody>` +
    B.cl.slice(0, 8).map((b) => `<tr><td><b>${esc(b.name)} ${b.side === 1 ? "多" : "空"}</b><small>${esc(b.rule)} · ${dts(b.t_in)}</small></td><td>${esc(b.why || "")}<small>${b.t_out ? dts(b.t_out) : ""}</small></td><td class="n"><b style="color:var(${b.u >= 0 ? "--good" : "--bad"})">${u1(b.u)}</b></td></tr>`).join("") +
    `</tbody></table>` : `<p class="note">还没有平掉的模拟单。</p>`;
  box.querySelectorAll("button[data-sym]").forEach((b2) => b2.addEventListener("click", () => goSym(b2.dataset.sym)));
  slideLanes(box);
}

// 持仓尺：左边止损（没填就用建议止损，虚线），右边止盈/2倍止损距离；开仓价一根线，现价一个点
function railHTML(key, q, f) {
  if (!q || !(q.E > 0) || !(q.last > 0)) return "";
  const up = q.side === 1, pts = [q.E, q.last].concat([q.stop, q.target, q.one].filter((x) => isFinite(x) && x > 0));
  const liqOn = q.liq > 0 && Math.abs(q.liq / q.last - 1) < 0.12; if (liqOn) pts.push(q.liq);
  let lo = Math.min(...pts), hi = Math.max(...pts); const pad = (hi - lo) * 0.06 || q.last * 0.01; lo -= pad; hi += pad;
  if (q.dom) { lo = q.dom.lo; hi = q.dom.hi; }
  const X = (v) => (up ? (v - lo) / (hi - lo) : (hi - v) / (hi - lo));          // 空单反过来画：右边永远是赚钱的方向
  const zones = [], ticks = [];
  const locked = isFinite(q.stop) && q.side * (q.stop - q.E) >= 0, side = (x) => (x > 0.62 ? " r" : x < 0.38 ? " l" : "");
  if (isFinite(q.stop) && !locked) zones.push([Math.min(X(q.stop), X(q.E)), Math.max(X(q.stop), X(q.E)), "dn"]);
  const from = locked ? q.stop : q.E;
  if (isFinite(q.target)) zones.push([Math.min(X(from), X(q.target)), Math.max(X(from), X(q.target)), "up"]);
  else if (locked) zones.push([X(q.stop), 1, "up"]);
  if (liqOn) ticks.push([X(q.liq), "强平", "liq"]);
  if (isFinite(q.stop) && !q.noStop) ticks.push([X(q.stop), `${q.sug ? "建议止损" : "止损"} ${f(q.stop)}`, "st" + (q.sug ? " sug" : "") + side(X(q.stop))]);
  if (q.noStop && isFinite(q.rule)) ticks.push([X(q.rule), "规则", "rs"]);
  ticks.push([X(q.E), `开 ${f(q.E)}`, "en" + side(X(q.E))]);
  if (isFinite(q.one) && !locked) ticks.push([X(q.one), "", "one"]);
  if (isFinite(q.target)) ticks.push([X(q.target), `${q.tgtLb} ${f(q.target)}`, "tg" + side(X(q.target))]);
  const pnl = q.side * (q.last - q.E);
  const rng = q.noStop ? `<input type="range" class="stop-rng${q.sug ? " sug" : ""}" min="0" max="1000" step="1" value="${Math.round(Math.max(0, Math.min(1, X(q.stop))) * 1000)}" aria-label="拖动设置止损价">` : "";
  const inner = trackHTML({ key, x: X(q.last), zones, ticks, dot: pnl >= 0 ? "up" : "dn" });
  return `<span class="rail">${rng ? inner.replace(/<\/span>$/, rng + "</span>") : inner}</span>`;
}
// ---------------------------------------------------------------- 止损拉杆：拖动或输入自己的止损，实时给分析；松手/输完才保存
let STOPDRAG = false, POSPEND = false;
function dayVol(sym) {
  const X = H1[sym]; if (!X) return NaN; const R = X.rows, r = [];
  for (let i = R.length - 1; i - 24 >= 0 && r.length < 20; i -= 24) r.push(Math.log(R[i].c / R[i - 24].c));
  if (r.length < 8) return NaN; const m = r.reduce((a, b) => a + b, 0) / r.length;
  return Math.sqrt(r.reduce((a, b) => a + (b - m) * (b - m), 0) / (r.length - 1));
}
const PhiN = (z) => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2), q = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - q : q; };
const STOPCTX = {};
function stopAnalysis(c, S) {
  const { p, last, rule, acct, sd, f, up } = c, qty = p.Q > 0 ? p.Q : p.N > 0 ? p.N / last : NaN, out = [];
  if (!(p.side * (last - S) > 0)) return `<b class="bad">这个价现在已经${up ? "跌破" : "涨过"}了，放这里止损会马上触发。</b>`;
  if (p.liq > 0 && p.side * (S - p.liq) <= 0) out.push(`<b class="bad">在强平价 ${f(p.liq)} 外面：会先爆仓再止损，要么挪近，要么减仓。</b>`);
  const uS = isFinite(qty) ? qty * p.side * (S - p.E) : NaN, lim = acct > 0 ? acct * 0.005 : NaN;
  if (isFinite(uS)) {
    if (uS >= 0) out.push(`打到也是<b class="g">赚 ${uS.toFixed(1)}U</b>，利润锁住了。`);
    else {
      let t = `打到亏 <b>${(-uS).toFixed(1)}U</b>${acct > 0 ? `（本金的 ${(-uS / acct * 100).toFixed(2)}%）` : ""}`;
      if (isFinite(lim)) t += -uS <= lim * 1.05 ? `，在每笔上限 ${lim.toFixed(0)}U 以内 ✓` : `，<b class="bad">超过每笔上限 ${lim.toFixed(0)}U</b>：要么止损挪到 ${f(p.E - p.side * lim / qty)}，要么持仓价值降到约 ${(p.N * lim / -uS).toFixed(0)}U`;
      out.push(t + "。");
    }
  }
  const z = Math.abs(Math.log(S / last));
  if (isFinite(sd) && sd > 0) {
    const k = z / sd, p1 = 2 * (1 - PhiN(k)), p3 = 2 * (1 - PhiN(k / Math.sqrt(3)));
    out.push(`离现价 ${pabs(z)}，约 ${k.toFixed(1)} 天的正常波动；按最近20天的波动，1天内被碰到的概率约 <b>${Math.round(p1 * 100)}%</b>，3天内约 <b>${Math.round(p3 * 100)}%</b>。`);
    if (k < 0.5 && !(uS >= 0)) out.push(`<b class="warnc">太近了，一天的正常晃动就容易扫掉。</b>`);
  }
  if (isFinite(rule)) { const w = p.side * (rule - S) / last; out.push(`规则建议 ${f(rule)}${Math.abs(w) < 0.002 ? "，和你的差不多" : `，你的比它${w > 0 ? "宽" : "窄"} ${pabs(Math.abs(w))}`}。`); }
  return out.join(" ");
}
function stopFromX(c, x) { const v = c.up ? c.lo + x * (c.hi - c.lo) : c.hi - x * (c.hi - c.lo); return v; }
function stopToX(c, v) { return Math.max(0, Math.min(1, c.up ? (v - c.lo) / (c.hi - c.lo) : (c.hi - v) / (c.hi - c.lo))); }
function stopClamp(c, v) { const lim = c.last * (1 - c.p.side * 0.0008); return c.up ? Math.min(v, lim) : Math.max(v, lim); }
function saveStop(sym, v) {
  const c = STOPCTX[sym]; if (!c) return; const o = loadPos(sym);
  o.S = isFinite(v) ? String(+v.toFixed(c.dp)) : ""; savePos(sym, o);
  const pb = $("posBox"); if (pb && pb.dataset.sym === sym) pb.dataset.sym = "";
}
function initStopBars() {
  const el = $("posList"); if (!el || el.dataset.sb) return; el.dataset.sb = "1";
  const ctxOf = (t) => { const r = t.closest(".pos-row"); return r ? [r, STOPCTX[r.dataset.sym]] : [null, null]; };
  const show = (row, c, v, fromNum) => {
    const an = row.querySelector(".stop-an"), num = row.querySelector(".stop-num"), rg = row.querySelector(".stop-rng");
    if (an) an.innerHTML = stopAnalysis(c, v);
    if (!fromNum && num) num.value = fmt(v, c.dp).replace(/,/g, "");
    if (fromNum && rg) rg.value = Math.round(stopToX(c, v) * 1000);
    if (rg) rg.classList.remove("sug");
  };
  el.addEventListener("input", (e) => {
    const [row, c] = ctxOf(e.target); if (!c) return;
    if (e.target.classList.contains("stop-rng")) { STOPDRAG = true; let v = stopClamp(c, stopFromX(c, +e.target.value / 1000)); e.target.value = Math.round(stopToX(c, v) * 1000); show(row, c, v, false); }
    else if (e.target.classList.contains("stop-num")) { const v = numv(e.target.value); if (v > 0) show(row, c, v, true); }
  });
  el.addEventListener("change", (e) => {
    const [row, c] = ctxOf(e.target); if (!c) return;
    if (e.target.classList.contains("stop-rng")) { const shown = numv((row.querySelector(".stop-num") || {}).value); saveStop(c.p.sym, shown > 0 ? shown : stopClamp(c, stopFromX(c, +e.target.value / 1000))); }
    else if (e.target.classList.contains("stop-num")) { const v = numv(e.target.value); saveStop(c.p.sym, v > 0 ? v : NaN); }
    else return;
    STOPDRAG = false; POSPEND = false; renderPosList(); if (window.JSQ && window.JSQ.state.sym === c.p.sym) renderCard(true);
  });
  const end = () => { if (STOPDRAG) { STOPDRAG = false; if (POSPEND) { POSPEND = false; setTimeout(renderPosList, 50); } } };
  el.addEventListener("pointerup", end); el.addEventListener("touchend", end);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList.contains("stop-num")) e.target.blur(); });
}
const POSPLAN = {};
function renderSlots(P) {
  const el = $("posSlots"); if (!el) return;
  const n = {}; for (const p of P) { const g = U.groupOfSym(p.sym); n[g] = (n[g] || 0) + 1; }
  const acct = numv(($("posAcct") || {}).value), per = acct > 0 ? acct * 0.005 : NaN;
  const G = [["crypto", "币", 4], ["stock", "股票", 3], ["metal", "金银", 2]];
  el.innerHTML = G.map(([g, nm, cap]) => { const k = n[g] || 0, over = k > cap;
    return `<span class="slot${over ? " over" : ""}"><small>${nm}</small>${Array.from({ length: Math.max(cap, k) }, (_, i) => `<i class="${i < k ? (i >= cap ? "x" : "on") : ""}"></i>`).join("")}</span>`; }).join("") +
    (isFinite(per) ? `<span class="slot per"><small>每笔最多亏</small><b class="num">${per.toFixed(0)}U</b></span>` : "");
}
async function renderPosList() {
  const box = $("posPanel"); if (!box) return;
  const ae = document.activeElement;
  if (STOPDRAG || (ae && ae.classList && ae.classList.contains("stop-num"))) { POSPEND = true; return; }
  initStopBars();
  const P = allPos(); box.hidden = false; renderBN(); renderSlots(P);
  for (const k of Object.keys(POSPLAN)) if (!P.some((p) => p.sym === k)) delete POSPLAN[k];
  if (!P.length) renderTodo();
  if (!P.length) { $("posList").innerHTML = ""; $("posSum").innerHTML = bnKeys() ? "币安合约账户现在没有仓位。" : "还没有仓位。连上币安（下面），开了仓会自动出现在这里；也可以在每个品种卡片的\"我已经有仓位\"里手填。"; return; }
  try { await needPrices(); } catch (e) {}
  await Promise.allSettled(P.map((p) => needH1(p.sym).then(() => statKey(p.sym) === "stock_main" ? needVol(p.sym) : 0)));
  const GN = { metal: "金银等商品", crypto: "币", stock: "股票" }, sum = {}, miss = [];
  let tot = 0, totNow = 0, known = true;
  const RK = { bad: 0, ok: 1, warn: 2, flat: 3 };
  const rows = P.map((p) => {
    const last = PX.m[p.sym] || (H1[p.sym] || {}).last, nm = U.names[p.sym] || p.sym.replace(/USDT$/, ""), dp = last >= 100 ? 2 : last >= 1 ? 3 : 5, f = (x) => fmt(x, dp);
    const qty = p.Q > 0 ? p.Q : p.N > 0 && last > 0 ? p.N / last : NaN, pn = isFinite(qty) ? qty * p.side * (last - p.E) : NaN, ps = isFinite(qty) && isFinite(p.S) ? qty * p.side * (p.S - p.E) : NaN;
    if (!isFinite(ps)) { miss.push(nm); known = false; } else { const g = U.groupOfSym(p.sym); sum[g] = (sum[g] || 0) + ps; tot += ps; }
    if (isFinite(pn)) totNow += pn;
    const u1 = (x) => isFinite(x) ? `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(1)}U` : "—";
    let pl = null; try { pl = posPlan(p.sym, p, last, dp, posCtx(p.sym, p.side)); } catch (e) {}
    if (pl) POSPLAN[p.sym] = { act: pl.act, cls: pl.cls, name: nm, side: p.side };
    const act = (pl && pl.act ? `<em class="pa ${pl.cls}">${pl.act}</em>` : "") + (pl && pl.addTxt && !/平掉/.test(pl.act) ? `<em class="pa-add">${pl.addTxt}</em>` : "");
    // 止损拉杆：规则建议的止损（不看你填的）当参照；没填就先放在建议上（虚线把手），拖了/填了才算你的
    let bar = "";
    if (pl && last > 0) {
      let rule = NaN; try { const r0 = posPlan(p.sym, Object.assign({}, p, { S: NaN }), last, dp, posCtx(p.sym, p.side)); rule = r0 && r0.nums ? r0.nums.stop : NaN; } catch (e) {}
      const sd = dayVol(p.sym) || (VOL[p.sym] || {}).sd || 0.025, up = p.side === 1, S0 = isFinite(p.S) ? p.S : isFinite(rule) ? rule : last * (1 - p.side * 2 * sd);
      const pts = [p.E, last, S0, rule, pl.nums.target, pl.nums.one, last * Math.exp(-p.side * 3 * sd)].filter((x) => isFinite(x) && x > 0);
      if (p.liq > 0 && Math.abs(p.liq / last - 1) < 0.15) pts.push(p.liq);
      let lo = Math.min(...pts), hi = Math.max(...pts); const pad = (hi - lo) * 0.05; lo -= pad; hi += pad;
      const acct = numv(($("posAcct") || {}).value);
      const c = STOPCTX[p.sym] = { p, last, rule, acct, sd, f, up, lo, hi, dp: last >= 100 ? 2 : last >= 1 ? 4 : 6 };
      const q = Object.assign({}, pl.nums, { stop: S0, sug: !isFinite(p.S), noStop: true, rule, dom: { lo, hi } });
      bar = `<div class="stopbar">${railHTML("r-" + p.sym, q, f)}<div class="stop-io"><label>我的止损<input class="stop-num" inputmode="decimal" autocomplete="off" value="${isFinite(p.S) ? fmt(p.S, c.dp).replace(/,/g, "") : ""}" placeholder="${fmt(S0, c.dp).replace(/,/g, "")}"></label>` +
        `<span class="stop-tip">${isFinite(p.S) ? "拖红色把手或改数字" : "还没填：把手先放在规则建议上，拖一下或填数字就记住"}</span></div><p class="stop-an">${stopAnalysis(c, S0)}</p></div>`;
    }
    return { k: pl ? RK[pl.cls] ?? 3 : 4, h: `<div class="pos-row" data-sym="${esc(p.sym)}"><button type="button" class="scan-row" data-sym="${esc(p.sym)}"><b>${esc(nm)} ${p.side === 1 ? "多" : "空"}</b><span>开 ${f(p.E)} → 现 ${last ? f(last) : "—"}｜${isFinite(pn) ? (pn >= 0 ? "浮盈 " : "浮亏 ") + u1(pn).replace(/^[+−]/, "") : ""}｜${isFinite(p.S) ? `止损 ${f(p.S)}（打到 ${u1(ps)}）` : "没填止损"}${p.liq > 0 ? `｜强平 ${f(p.liq)}` : ""}${act}</span></button>${bar}</div>` };
  }).sort((x, y) => x.k - y.k).map((x) => x.h);
  $("posList").innerHTML = rows.join("");
  const acct = numv(($("posAcct") || {}).value), pc = (x) => acct > 0 ? `，本金的 ${(Math.abs(x) / acct * 100).toFixed(1)}%` : "";
  const parts = Object.keys(sum).map((g) => `${GN[g]} ${sum[g] >= 0 ? "+" : "−"}${Math.abs(sum[g]).toFixed(1)}U`);
  let t = `${P.length} 个仓位，现在合计 ${totNow >= 0 ? "+" : "−"}${Math.abs(totNow).toFixed(1)}U。<b>如果全部打到止损：${tot >= 0 ? "还赚" : "一共亏"} ${Math.abs(tot).toFixed(1)}U</b>${tot < 0 ? pc(tot) : ""}` + (parts.length > 1 ? `（${parts.join("，")}）` : "") + "。";
  if (miss.length) t += ` ${miss.join("、")} 没填止损，没算进去（点那一行，在"我已经有仓位"里填）。`;
  // 账户规则（近5年回测 research/risk_bt.py）：每笔止损最多亏本金0.5%；同时最多 币4 / 股票3 / 金银2
  const CAP = { crypto: 4, stock: 3, metal: 2 }, cnt = {}, big = [];
  for (const p of P) { const g = U.groupOfSym(p.sym); cnt[g] = (cnt[g] || 0) + 1;
    const last = PX.m[p.sym] || (H1[p.sym] || {}).last, qty = p.Q > 0 ? p.Q : p.N > 0 && last > 0 ? p.N / last : NaN, ps = isFinite(qty) && isFinite(p.S) ? qty * p.side * (p.S - p.E) : NaN;
    if (acct > 0 && isFinite(ps) && -ps > acct * 0.005 * 1.2) big.push(`${U.names[p.sym] || p.sym.replace(/USDT$/, "")}（打到止损亏 ${(-ps).toFixed(0)}U）`); }
  const over = Object.keys(cnt).filter((g) => cnt[g] > (CAP[g] || 99));
  const lim = acct > 0 ? (acct * 0.005).toFixed(0) : "16";
  t += `<br><b>账户规则</b>：每笔止损打到最多亏 ${lim}U（本金0.5%）；同时最多 币4个、股票3个、金银2个。`;
  if (!(acct > 0)) t += ` 右上角填上本金，我才能帮你对照。`;
  if (over.length) t += ` <b class="bad">${over.map((g) => `${GN[g]}现在 ${cnt[g]} 个，超了（上限 ${CAP[g]}）`).join("；")}</b>：同一类一跌一起跌，新的先别开。`;
  if (big.length) t += ` <b class="bad">这几笔单笔风险偏大：${big.join("、")}</b>，可以减一点仓或把止损挪近。`;
  if (acct > 0 && !over.length && !big.length && !miss.length) t += ` 现在都在规则内。`;
  $("posSum").innerHTML = t;
  $("posList").querySelectorAll("button.scan-row").forEach((b) => b.addEventListener("click", () => goSym(b.dataset.sym, "posBox")));
  slideLanes($("posList")); renderTodo();
}
// ---------------------------------------------------------------- 我的持仓：按规则算止损、止盈和后续（只存在这台手机）
const numv = (x) => { const v = parseFloat(String(x || "").replace(/[,，\s]/g, "")); return isFinite(v) ? v : NaN; };
function loadPos(sym) { try { return JSON.parse(localStorage.getItem("jsq.pos." + sym) || "{}") || {}; } catch (e) { return {}; } }
function savePos(sym, o) { try { if (o.E) localStorage.setItem("jsq.pos." + sym, JSON.stringify(o)); else localStorage.removeItem("jsq.pos." + sym); } catch (e) {} }
// 一笔已有仓位的计划（卡片"我已经有仓位"和首页"我的持仓"共用）。p = {side, E, S, N, Q(数量), liq}；返回 { L: 详细几行, act: 一句话现在该做什么, cls }
function posCtx(sym, side) {
  const g = U.groupOfSym(sym), env = envFor(sym), dipMode = statKey(sym) === "stock_main" && !!env && !env.bull;
  const okDir = !!env && (side === 1 ? dipMode || OKG(grade(statFor(sym, env.bull, "long"))) || (env.bull && statKey(sym) === "stock_main" && ndxDipped()) : OKG(grade(statFor(sym, env.bull, "short"))));
  return { g, env, dipMode, okDir };
}
function posPlan(sym, p, last, dp, ctx) {
  const X = H1[sym]; if (!X || !(p.E > 0) || !(last > 0)) return null;
  const { g, dipMode, okDir } = ctx, side = p.side === -1 ? -1 : 1, up = side === 1, E = p.E, S = p.S, f = (x) => fmt(x, dp), L = [];
  const qty = p.Q > 0 ? p.Q : p.N > 0 ? p.N / last : NaN, uAt = (px) => isFinite(qty) ? qty * side * (px - E) : NaN;
  const money = (px) => { const u = uAt(px); return isFinite(u) ? `（${u >= 0 ? "赚" : "亏"}约 ${Math.abs(u).toFixed(1)}U）` : ""; };
  const pnow = side * (last - E);
  const sInfo = isFinite(S) ? (side * (S - E) >= 0 ? `你现在的止损 ${f(S)} 已经在开仓价${up ? "上方" : "下方"}，锁住了一部分利润${money(S)}。` : `你现在的止损 ${f(S)}${money(S)}。`) : "";
  L.push(`现价 ${f(last)}，${pnow >= 0 ? "浮盈" : "浮亏"} ${pabs(pnow / E, 2)}${money(last)}。${sInfo}`);
  let act = "", cls = "flat", nums = {};
  const warn = [];
  // 风险检查：止损已经被穿过 / 止损在强平价外面 / 没止损但离强平近
  if (isFinite(S) && side * (last - S) <= 0) warn.push([`已经${up ? "跌破" : "涨过"}你的止损 ${f(S)}：现在平掉`, `现价已经${up ? "跌破" : "涨过"}你的止损 ${f(S)}：按计划这单应该已经出场了，币安上要是没设止损单，现在就平。`]);
  if (p.liq > 0 && isFinite(S) && side * (S - p.liq) <= 0) warn.push([`止损 ${f(S)} 在强平价 ${f(p.liq)} ${up ? "下面" : "上面"}，会先爆仓`, `你的止损 ${f(S)} 在强平价 ${f(p.liq)} ${up ? "下面" : "上面"}，会先爆仓再止损：要么把止损挪到强平价${up ? "上方" : "下方"}，要么减仓或加保证金。`]);
  if (p.liq > 0 && !isFinite(S) && Math.abs(last / p.liq - 1) < 0.1) warn.push([`没设止损，离强平价 ${f(p.liq)} 只差 ${pabs(last / p.liq - 1)}`, `没设止损，离强平价 ${f(p.liq)} 只差 ${pabs(last / p.liq - 1)}。`]);
  // 熊市里"大跌后止跌"买的单，纳指转牛以后照样按那一套管完（开仓价在这一轮止跌点附近才算这一轮的单）
  const ep = (dipMode || statKey(sym) === "stock_main") && up && g === "stock" && VOL[sym] ? dipEpisode(X.sess, VOL[sym].sd) : null;
  const epUse = ep && (ep.stage === "open" || ep.stage === "done") ? ep : ep && ep.last ? ep.last : null;
  if (epUse && epUse.top > E && (dipMode || E < epUse.E0 + 0.5 * (epUse.top - epUse.E0))) {
    const R = E - epUse.stop, one = E + R, half = E + 0.5 * R;
    nums = { stop: isFinite(S) ? S : epUse.stop, target: epUse.top, one: R > 0 ? one : NaN, tgtLb: "止盈", dip: true };
    L.push(`<b>按"回调企稳"这一套管</b>（这一轮 ${nyInfo(epUse.kt).md} 在 ${f(epUse.E0)} 企稳${epUse.stage === "done" ? "，按规则这一轮已经" + epUse.why : ""}）：`);
    const locked = isFinite(S) && S >= E;
    if (locked) L.push(`① 你的止损 ${f(S)} 已经在开仓价上方，利润锁住了，不用再挪；止损只往上挪，不往下放。`);
    else if (R > 0) L.push(last >= one ? `① 已经过了1倍止损距离（${f(one)}）：止损至少挪到开仓价 <b>${f(E)}</b>，或开仓价上方半份 <b>${f(half)}</b>${money(half)}——两种回测平均差不多，后一种46次里91%最后是赚的。止损只往上挪，不往下放。`
      : `① 规则止损 <b>${f(epUse.stop)}</b>${money(epUse.stop)}${isFinite(S) && Math.abs(S / epUse.stop - 1) > 0.003 ? `（你填的是 ${f(S)}）` : ""}；涨到 <b>${f(one)}</b> 再把止损挪到开仓价（或开仓价上方半份 ${f(half)}）。`);
    L.push(`② 止盈：<b>${f(epUse.top)}</b>（跌够那一刻的5天高点）一次全平${money(epUse.top)}。这一套回测里先平一半、剩下不封顶并没有更好。`);
    L.push(`③ 时间：最晚 <b>${epUse.deadline}</b> 美股收盘，没到目标也没碰止损就手动平。`);
    L.push(`④ 不加仓；平掉以后等下一轮"跌够+企稳"再进。`);
    if (last >= epUse.top) { act = `已经过了止盈价 ${f(epUse.top)}：按计划现在全部平掉${money(last)}`; cls = "ok"; L.unshift(`<b class="ok">现价 ${f(last)} 已经过了这笔单的止盈价 ${f(epUse.top)}：按计划现在全部平掉${money(last)}。</b>`); }
    else if (epUse.stage === "done") { act = /止盈/.test(epUse.why) ? `这一轮已经碰过止盈价 ${f(epUse.top)}：按计划现在平掉${money(last)}` : /到期/.test(epUse.why) ? `已经拿满10个交易日（${epUse.deadline}）：按计划现在平掉${money(last)}` : `按规则这一轮已经${epUse.why}：还拿着的话现在平掉${money(last)}`; cls = /止盈/.test(epUse.why) ? "ok" : "warn"; }
    else if (locked) { act = `止损 ${f(S)} 不动（利润已锁）；止盈 ${f(epUse.top)}，最晚 ${epUse.deadline} 平`; cls = "ok"; }
    else if (R > 0 && last >= one) { act = `止损挪到开仓价 ${f(E)} 或 ${f(half)}；止盈 ${f(epUse.top)}，最晚 ${epUse.deadline} 平`; cls = "ok"; }
    else act = `止损 ${f(isFinite(S) ? S : epUse.stop)}；涨到 ${f(one)} 挪保本；止盈 ${f(epUse.top)}，最晚 ${epUse.deadline} 平`;
  } else {
    // 突破那一套：1R保本 → 跟踪3天低点，不设固定止盈，可选2R先平一半
    const rows = g === "stock" && X.sess.length >= 21 ? X.sess : X.rows, n = rows.length, k3 = g === "stock" ? 21 : 72, kL = g === "stock" ? 7 : 24;
    const ext = up ? minL(rows, n - k3, n) : maxH(rows, n - k3, n), trail = up ? Math.max(E, ext) : Math.min(E, ext);
    const R = isFinite(S) && side * (E - S) > 0 ? side * (E - S) : NaN, locked = isFinite(S) && side * (S - E) >= 0;
    nums = { stop: isFinite(S) ? S : NaN, target: isFinite(R) ? E + side * 2 * R : NaN, one: isFinite(R) ? E + side * R : NaN, tgtLb: "2倍" };
    L.push(`<b>按"突破"这一套管</b>（不设固定止盈）：`);
    if (locked) {
      const nst = up ? Math.max(S, trail) : Math.min(S, trail);
      L.push(`① 你的止损 ${f(S)} 已经在开仓价${up ? "上方" : "下方"}，利润锁住了。之后止损跟着"过去3天${up ? "最低" : "最高"}点"挪：现在是 ${f(ext)}，所以止损放 <b>${f(nst)}</b>${money(nst)}，只往有利方向挪，碰到就走。`);
      L.push(`② 不设固定止盈，让行情自己跑。`);
      act = side * (nst - S) > 0 ? `止损挪到 ${f(nst)}${money(nst)}，之后跟着3天${up ? "最低" : "最高"}点挪` : `止损 ${f(S)} 不动（利润已锁），之后跟着3天${up ? "最低" : "最高"}点挪`; cls = "ok";
    } else if (isFinite(R)) {
      const one = E + side * R, two = E + side * 2 * R, past1 = side * (last - one) >= 0;
      L.push(past1 ? `① 已经过了1倍止损距离（${f(one)}）：止损挪到开仓价 <b>${f(E)}</b>。` : `① 止损先放在 ${f(S)}；${up ? "涨" : "跌"}到 <b>${f(one)}</b>（1倍止损距离）再挪到开仓价。`);
      L.push(past1 ? `② 之后止损跟着"过去3天${up ? "最低" : "最高"}点"挪：现在是 ${f(ext)}，所以止损放 <b>${f(trail)}</b>${money(trail)}，只往有利方向挪，碰到就走。`
        : `② 过了1倍以后，止损再改成跟着"过去3天${up ? "最低" : "最高"}点"挪（只往有利方向挪，碰到就走）。`);
      L.push(`③ 想分批：到 <b>${f(two)}</b>（2倍）先平一半${money(two)}，剩下照样跟踪。`);
      if (past1) { const nst = up ? Math.max(S, trail) : Math.min(S, trail); act = side * (nst - S) > 0 ? `止损挪到 ${f(nst)}${money(nst)}，之后跟着3天${up ? "最低" : "最高"}点挪` : `止损 ${f(S)} 不动，之后跟着3天${up ? "最低" : "最高"}点挪`; cls = "ok"; }
      else act = `止损 ${f(S)}；${up ? "涨" : "跌"}到 ${f(one)} 把止损挪到开仓价`;
    } else if (pnow > 0) {
      L.push(`① 止损跟着"过去3天${up ? "最低" : "最高"}点"挪：现在是 ${f(ext)}，止损放 <b>${f(trail)}</b>${money(trail)}（${up ? "不低于" : "不高于"}开仓价），只往有利方向挪。`);
      L.push(`② 不设固定止盈，让行情自己跑；想分批就在浮盈到开仓时止损距离的2倍时先平一半。`);
      act = `没设止损：放 ${f(trail)}${money(trail)}，之后跟着3天${up ? "最低" : "最高"}点挪`; cls = "warn"; nums.stop = trail; nums.sug = true;
    } else {
      const rs = up ? minL(rows, n - kL, n) * 0.999 : maxH(rows, n - kL, n) * 1.001, w = g === "stock" ? "最近7根交易时段小时线" : "最近24小时";
      L.push(`① 现在还没盈利、也没填止损：按规则止损放${w}${up ? "最低" : "最高"}点外 <b>${f(rs)}</b>${money(rs)}（开仓时的止损你要是记得，填在"现在的止损"里更准）。`);
      L.push(`② ${up ? "涨" : "跌"}到止损距离的1倍再挪到开仓价；不设固定止盈。`);
      act = `没设止损：按规则放 ${f(rs)}${money(rs)}`; cls = "warn"; nums.stop = rs; nums.sug = true;
    }
  }
  // 赚了再加（research/add_winners_bt.py，5年顺势开的单子）：做多到1倍止损距离再加一份，全部止损挪到第一笔开仓价；空单不加；亏着永远不加
  const S1 = isFinite(S) ? S : nums.stop, Rx = isFinite(S1) ? side * (E - S1) : NaN, N1 = p.N > 0 ? p.N : NaN;
  let addTxt = "";
  if (nums.dip) { L.push(`<b>加仓</b>：大跌后企稳的单子有固定止盈，一次性开，不加仓（加仓没验证过）。`); addTxt = "加仓：这类单子不加"; }
  else if (!up) { L.push(`<b>加仓</b>：空单不加（回测里空单加仓平均反而变差）。亏着的单子永远不加。`); addTxt = "加仓：空单不加"; }
  else if (isFinite(Rx) && Rx > 0) {
    const a1 = E + Rx, a2 = E + 2 * Rx, more = g === "crypto" ? `；再涨到 <b>${f(a2)}</b> 可以再加一份，全部止损挪到 ${f(a1)}` : g === "stock" ? "；股票只加这一次（隔夜跳空，加两次最差一笔会大很多）" : "；金银只加这一次（再加没更好）";
    addTxt = last < a1 ? `加仓：涨到 ${f(a1)} 再加一份，全部止损挪到 ${f(E)}；亏着不加` : `加仓：1倍已到过，没加就不追加`;
    L.push(last < a1 ? `<b>赚了再加</b>：涨到 <b>${f(a1)}</b>（1倍止损距离）再加一份同样大的${isFinite(N1) ? `（约 ${N1.toFixed(0)}U 持仓价值）` : ""}，加完把<b>全部止损挪到 ${f(E)}</b>，这样加了仓也亏不了${more}。亏着的时候永远不加。`
      : `<b>赚了再加</b>：已经到过 ${f(a1)}（1倍止损距离）。那时加了一份的话，全部止损应该在 ${f(E)} 或更高${g === "crypto" && last < a2 ? `，涨到 ${f(a2)} 还能再加一份` : ""}；没加就不追着加了（回测是到价那一刻加）。`);
    L.push(`<span class="plan-bt">回测（5年里顺着走势开的多单）：涨到1倍止损距离再加一份，每笔平均 币 +1.5U→+3.2U、股票 +5.6U→+8.3U、金银 +1.6U→+2.9U，前后两段都更好，最差一笔基本不变（股票隔夜跳空例外）；亏着再加（拉均价）每一组都更差，最差一笔大一倍。</span>`);
  } else if (isFinite(Rx) && Rx <= 0) L.push(`<b>加仓</b>：止损已经在开仓价${up ? "上方" : "下方"}，按这套第一份加仓应该已经加过；之后只挪止损，不再加。`);
  if (p.avgDn && Date.now() - p.avgDn < 3 * 864e5) warn.push([`刚才是亏着加仓（拉均价），别再加`, `你刚才是在亏着的时候加仓（拉均价）：回测里亏了再加，最差一笔亏损大一倍左右，你以前的大亏也是这样来的。别再加，按止损走。`]);
  if (!okDir) L.push(`<span class="plan-bt">提醒：按回测，现在这种环境${up ? "做多" : "做空"}这个品种本来不做（或样本太少）；已经在里面就按上面管，别加仓。</span>`);
  if (warn.length) { L.unshift(`<b class="bad">${warn.map((w) => w[1]).join(" ")}</b>`); if (!/平掉/.test(act)) { act = warn[0][0]; cls = "bad"; } }
  return { L, act, cls, okDir, addTxt, nums: Object.assign(nums, { E, last, side, liq: p.liq }) };
}
function renderPos(sym, V, env, g, dipMode, okDir) {
  const box = $("posBox"); if (!box || !V) return;
  if (box.dataset.sym !== sym) {
    box.dataset.sym = sym; const o = loadPos(sym);
    $("posSide").value = String(o.side || 1); $("posE").value = o.E || ""; $("posS").value = o.S || ""; $("posN").value = o.N || "";
    if (o.E) box.open = true;
    const bn = o.src === "bn"; ["posSide", "posE", "posN"].forEach((id) => { const e = $(id); if (e) e.disabled = bn; });
    const nt = $("posNote"); if (nt) nt.textContent = bn ? "方向、开仓价、持仓价值是币安读来的，每分钟自动更新；你只需要填止损（币安的止损单读不到）。" : "只存在这台手机，换品种会记住各自的仓位；清空开仓价就删掉。";
  }
  const side = +$("posSide").value, E = numv($("posE").value), S = numv($("posS").value), NV = numv($("posN").value), out = $("posOut");
  const o0 = loadPos(sym); savePos(sym, Object.assign(o0, { side, E: $("posE").value.trim(), S: $("posS").value.trim(), N: $("posN").value.trim() }));
  if (!(E > 0)) { out.innerHTML = "填开仓价就能算（持仓价值填币安上的\"持仓数量(USDT)\"）。"; return; }
  if (!H1[sym]) { needH1(sym).then((ch) => { if (ch && window.JSQ.state.sym === sym) renderCard(true); }).catch(() => {}); out.innerHTML = "正在取小时线…"; return; }
  const P = posPlan(sym, { side, E, S, N: NV, Q: numv(o0.Q), liq: numv(o0.liq), avgDn: +o0.avgDn || 0 }, V.last, V.dp, { g, dipMode, okDir });
  out.innerHTML = P ? P.L.join("<br>") : "";
}
// 币安后来新上的股票合约：数据管线每天检测（和美股价格对得上才算），这里补进'全部品种'
function mergePerps() {
  const L = (window.JSQ_ENV || {}).stock_perps; if (!Array.isArray(L)) return;
  for (const s of L) if (!U.all.includes(s)) { U.STOCKS.push(s); U.all.push(s); U.names[s] = U.names[s] || s.replace(/USDT$/, ""); }
}
// ---------------------------------------------------------------- 美股放量跳空（research/ep_bt.py）
function renderEP() {
  const E = window.JSQ_ENV || {}, L = E.ep, el = $("epList"), note = $("epNote");
  if (!el || !note) return;
  if (!Array.isArray(L)) { note.textContent = "数据下次更新后出现。"; el.innerHTML = ""; return; }
  const u = usNow(), bull = !!(u && u.bull);
  note.innerHTML = (bull ? `<b>现在纳指是牛市，这招可以做。</b>` : `<b>现在纳指是熊市，这招不做</b>（熊市里它是亏的），下面只是记录。`) +
    `<br>做法：股票因为财报或大消息，开盘直接跳高8%以上、成交量是平时3倍以上 → <b>第二天开盘做多</b>，止损放跳空那天的最低价，拿20个交易日。` +
    `<br><span class="src">历史成绩（纳指牛市，近5年243次）：平均每次 +3.3%，10次里赚3~4次，靠少数大涨赚钱。</span>`;
  if (!L.length) { el.innerHTML = `<p class="note">最近15个交易日没有符合条件的跳空。</p>`; return; }
  const addTD = (d, n) => { let x = new Date(d + "T12:00:00Z"), k = 0; while (k < n) { x = new Date(x.getTime() + 864e5); const w = x.getUTCDay(); if (w !== 0 && w !== 6) k++; } return `${x.getUTCMonth() + 1}月${x.getUTCDate()}日`; };
  el.innerHTML = L.map((e) => {
    const nm = esc((U.names[e.t + "USDT"] || e.t)), md = `${+e.d.slice(5, 7)}月${+e.d.slice(8, 10)}日`, end = addTD(e.d, 21);
    let st;
    if (e.last < e.low) st = `已经跌破止损位 ${e.low}，这次作废。`;
    else if (!bull) st = `纳指熊市，不做。`;
    else if (e.days === 0) st = `<b>下一个美股开盘做多</b>，止损 <b>${e.low}</b>（跳空那天最低价），拿到 <b>${end}</b> 收盘。仓位按止损距离算（止损打到最多亏本金0.5%）。`;
    else st = `进场时间已过（规则只在跳空第二天开盘买，当时 ${e.open1 ?? "—"}，晚买没验证过）。已经在里面的：止损 ${e.low}，拿到 ${end} 收盘。`;
    return `<div class="ep-row"><b class="t">${nm}</b> ${md} 跳空 +${(e.gap * 100).toFixed(1)}%，量 ${e.vol} 倍，现 ${e.last}<br><span class="st">${st}</span></div>`;
  }).join("");
}
// ---------------------------------------------------------------- 币安只读API：自动读合约持仓
// 密钥只存在这台手机（localStorage），只发给币安。用币安 WebSocket API（wss://ws-fapi.binance.com）读，
// 因为币安的 REST 接口不让网页直接带密钥访问（浏览器跨域限制），WebSocket 没这个限制。
// 签名：参数按名字排序拼成 a=1&b=2，HMAC-SHA256（Secret Key），十六进制。
const BN = { key: "jsq.bnkey", busy: false, at: 0, err: "", n: 0, off: NaN, acct: NaN, note: "" };
function bnKeys() { try { const o = JSON.parse(localStorage.getItem(BN.key) || "null"); return o && o.k && o.s ? o : null; } catch (e) { return null; } }
async function bnSign(secret, params) {
  const q = Object.keys(params).sort().map((k) => `${k}=${params[k]}`).join("&"), te = new TextEncoder();
  const ck = await crypto.subtle.importKey("raw", te.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return Array.from(new Uint8Array(await crypto.subtle.sign("HMAC", ck, te.encode(q)))).map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function bnTime() {
  try { const t0 = Date.now(), r = await fetch(`${REST}/fapi/v1/time`, { cache: "no-store" }), j = await r.json(); if (j && j.serverTime) BN.off = j.serverTime - (t0 + Date.now()) / 2; } catch (e) {}
  if (!isFinite(BN.off)) BN.off = 0;
}
function bnWS(calls) {
  return new Promise((resolve, reject) => {
    let ws; try { ws = new WebSocket("wss://ws-fapi.binance.com/ws-fapi/v1"); } catch (e) { reject(new Error("net")); return; }
    const out = calls.map(() => undefined); let done = 0;
    const fin = (f) => { clearTimeout(tm); try { ws.close(); } catch (e) {} f(); };
    const tm = setTimeout(() => fin(() => reject(new Error("net"))), 15000);
    ws.onopen = () => calls.forEach((c, i) => ws.send(JSON.stringify({ id: "jsq" + i, method: c.method, params: c.params })));
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      const i = +String(m.id || "").slice(3); if (!(i >= 0 && i < calls.length) || out[i] !== undefined) return;
      out[i] = m.status === 200 ? { ok: true, r: m.result } : { ok: false, e: m.error || { code: m.status } };
      if (++done === calls.length) fin(() => resolve(out));
    };
    ws.onerror = () => fin(() => reject(new Error("net")));
  });
}
function bnErr(e) {
  const c = e && e.code, msg = String((e && e.msg) || "");
  if (c === -2014 || c === -2008) return "API Key 填得不对（检查有没有多复制空格）。";
  if (c === -1022) return "Secret Key 填得不对。";
  if (c === -2015) return "币安拒绝了这个密钥：可能 Key 不对、没勾\"允许读取\"，或者设了IP白名单（这里要选\"不限制IP\"）。";
  if (c === -1021) return "手机时间和币安差太多，打开手机设置里的\"自动设置时间\"再试。";
  return `币安返回错误${c ? `（${c}）` : ""}${msg ? "：" + esc(msg.slice(0, 80)) : ""}。`;
}
async function bnSync(manual) {
  const K = bnKeys(); if (!K || BN.busy) return; BN.busy = true; BN.err = ""; if (manual) { BN.note = "正在读取…"; renderBN(); }
  try {
    if (manual || !isFinite(BN.off)) await bnTime();
    const mk = async (method) => { const p = { apiKey: K.k, recvWindow: 10000, timestamp: Math.round(Date.now() + BN.off) }; p.signature = await bnSign(K.s, p); return { method, params: p }; };
    const res = await bnWS([await mk("v2/account.position"), await mk("v2/account.status")]);
    if (!res[0] || !res[0].ok) throw Object.assign(new Error("api"), { bn: res[0] && res[0].e });
    // 同一个品种如果双向持仓，只取持仓价值大的那一边
    const got = {};
    for (const x of res[0].r || []) {
      const amt = +x.positionAmt; if (!amt || !x.symbol) continue;
      const side = x.positionSide === "SHORT" ? -1 : x.positionSide === "LONG" ? 1 : amt > 0 ? 1 : -1, nv = Math.abs(+x.notional) || Math.abs(amt * +x.markPrice);
      if (got[x.symbol] && got[x.symbol].nv >= nv) continue;
      got[x.symbol] = { side, E: +x.entryPrice, nv, q: Math.abs(amt), liq: +x.liquidationPrice, up: +x.unRealizedProfit };
    }
    const keys = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith("jsq.pos.")) keys.push(k); }
    for (const k of keys) if (!got[k.slice(8)]) localStorage.removeItem(k);            // 币安上已经平掉的
    for (const sym of Object.keys(got)) {
      const g = got[sym], old = loadPos(sym), same = +old.side === g.side && numv(old.E) > 0 && Math.abs(g.E / numv(old.E) - 1) < 0.05;
      const S = same && isFinite(numv(old.S)) ? old.S : "";                              // 止损：币安读不到条件单，同一笔单（方向一样、开仓价差不到5%）沿用你填过的
      let avgDn = +old.avgDn || 0, addUp = +old.addUp || 0;
      if (+old.side === g.side && numv(old.Q) > 0 && g.q > numv(old.Q) * 1.02) {             // 数量变多了 = 加了仓
        const mk = PX.m[sym] || (H1[sym] || {}).last || g.E;
        if (g.side * (mk - numv(old.E)) < 0) avgDn = Date.now(); else addUp = Date.now();
      }
      const dp = g.E >= 100 ? 2 : g.E >= 1 ? 4 : 6;
      savePos(sym, { side: g.side, E: String(+g.E.toFixed(dp)), S, N: String(+g.nv.toFixed(2)), Q: String(g.q), liq: g.liq > 0 ? String(+g.liq.toFixed(dp)) : "", src: "bn", avgDn, addUp });
    }
    BN.n = Object.keys(got).length;
    const a = res[1] && res[1].ok ? res[1].r : null, bal = a ? +(a.totalMarginBalance || a.totalWalletBalance) : NaN;
    if (bal > 0) { BN.acct = bal; try { localStorage.setItem("jsq.acct", String(Math.round(bal))); } catch (e) {} const ai = $("posAcct"); if (ai) ai.value = String(Math.round(bal)); }
    BN.at = Date.now(); BN.note = "";
    const pb = $("posBox"); if (pb) pb.dataset.sym = "";                                 // 让卡片里"我已经有仓位"重新读
  } catch (e) {
    BN.err = e && e.bn ? bnErr(e.bn) : "连不上币安（检查网络或梯子；能看行情说明网络是通的，过一会儿再点刷新）。"; BN.note = "";
    if (e && e.bn && [-2014, -2008, -1022, -2015].includes(e.bn.code) && !BN.at) { try { localStorage.removeItem(BN.key); } catch (x) {} BN.err += "改好以后重新粘贴。"; }
  }
  BN.busy = false; renderBN(); renderPosList(); renderCard(true);
}
function renderBN() {
  const K = bnKeys(), form = $("bnForm"), on = $("bnOn"), st = $("bnStat"), sm = $("bnSum"); if (!form || !on || !st) return;
  form.hidden = !!K; on.hidden = !K;
  const ai = $("posAcct"); if (ai) { ai.readOnly = !!K; const lb = ai.parentElement; if (lb && lb.firstChild && lb.firstChild.nodeType === 3) lb.firstChild.textContent = K ? "合约账户 U " : "本金 U（选填）"; }
  if (sm) sm.textContent = K ? "币安持仓：已连接（只读）" : "从币安自动读取持仓（只读）";
  const tm = BN.at ? new Date(BN.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
  st.innerHTML = BN.err ? `<b class="bad">${BN.err}</b>` : BN.note ? BN.note : K ? (BN.at ? `${tm} 读到 ${BN.n} 个仓位${BN.acct > 0 ? `，合约账户 ${BN.acct.toFixed(0)}U（已填进本金）` : ""}；页面开着每分钟自动更新。开仓价、方向、持仓价值、强平价从币安来；止损币安这边读不到，在品种卡片"我已经有仓位"里填一次就记住。` : "还没读取。") : "";
}
function initBN() {
  const sv = $("bnSave"), dl = $("bnDel"), rf = $("bnRef"); if (!sv) return;
  sv.addEventListener("click", () => {
    const k = $("bnK").value.trim(), s2 = $("bnS").value.trim();
    if (!/^[A-Za-z0-9]{20,100}$/.test(k) || !/^[A-Za-z0-9]{20,100}$/.test(s2)) { BN.err = "两个密钥都要填（一串字母数字，复制时别带空格）。"; renderBN(); return; }
    try { localStorage.setItem(BN.key, JSON.stringify({ k, s: s2 })); } catch (e) {}
    $("bnK").value = ""; $("bnS").value = ""; BN.err = ""; bnSync(true);
  });
  dl.addEventListener("click", () => {
    try { localStorage.removeItem(BN.key); const ks = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith("jsq.pos.") && (JSON.parse(localStorage.getItem(k) || "{}") || {}).src === "bn") ks.push(k); } ks.forEach((k) => localStorage.removeItem(k)); } catch (e) {}
    BN.at = 0; BN.err = ""; BN.note = "密钥已从这台手机删掉。记得也去币安 API 管理里把这个 API 删除。"; renderBN(); renderPosList(); renderCard(true);
  });
  if (rf) rf.addEventListener("click", () => bnSync(true));
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - BN.at > 30e3) bnSync(false); });
  renderBN(); if (bnKeys()) bnSync(false);
}
function initPos() {
  initBN();
  let tm = 0;
  ["posSide", "posE", "posS", "posN"].forEach((id) => { const e = $(id); if (e) e.addEventListener("input", () => { renderCard(true); clearTimeout(tm); tm = setTimeout(renderPosList, 800); }); });
  const a = $("posAcct"); if (a) { try { a.value = localStorage.getItem("jsq.acct") || ""; } catch (e) {} a.addEventListener("input", () => { try { localStorage.setItem("jsq.acct", a.value.trim()); } catch (e) {} renderPosList(); }); }
  setInterval(() => { if (!document.hidden) { scanAll(false); if (bnKeys()) bnSync(false); else renderPosList(); } }, 60e3);
}
function setDir(text, cls) { const d = $("cardDir"); d.textContent = text; d.className = "card-dir " + cls; }
function renderCard(force) {
  const J = window.JSQ; if (!J) return;
  const now = Date.now(), key = J.state.sym + "|" + J.state.tf;
  if (key !== lastKey) { force = true; lastKey = key; }
  if (!force && now - lastRender < 2000) { clearTimeout(timer); timer = setTimeout(() => renderCard(true), 2100); return; }
  lastRender = now;
  const sym = J.state.sym, tf = J.state.tf, name = U.names[sym] || sym, g = U.groupOfSym(sym);
  let V = J.VIEW;
  $("cardName").textContent = `${name} · ${J.TF_LABEL[tf] || tf}`;
  if (!V) { setDir("等行情载入…", "flat"); $("cardWhy").textContent = ""; $("cardTech").innerHTML = ""; $("cardPlan").innerHTML = ""; $("cardHist").textContent = ""; $("cardWarn").textContent = ""; $("cardVol").innerHTML = ""; return; }
  const T = tech(V, tf), env = envFor(sym);
  PLANNUM = null;
  needVol(sym).then((ch) => { if (ch && window.JSQ.state.sym === sym) renderCard(true); }).catch(() => {});
  const dipMode = statKey(sym) === "stock_main" && env && !env.bull;
  const bullDip = env && env.bull && statKey(sym) === "stock_main" && ndxDipped();   // 其他22只科技股同样条件只有 +1.4U/次，不用
  needH1(sym).then((ch) => { if (ch && window.JSQ.state.sym === sym) renderCard(true); }).catch(() => {});
  // 美股合约：突破价位按"最近7根交易时段小时线"算（回测口径），不用24小时
  const SS = g === "stock" && H1[sym] && H1[sym].sess.length >= 7 ? H1[sym].sess : null;
  if (SS && tf !== "1d") V = Object.assign({}, V, { H: maxH(SS, SS.length - 7, SS.length), L: minL(SS, SS.length - 7, SS.length), sess: true });
  if (g !== "stock") needDMA(g === "crypto" ? "BTCUSDT" : sym).then(() => { if (!env && envFor(sym)) renderCard(true); });
  // 技术面一行一行
  const IND = { "均线": "ma", "MACD": "macd", "RSI": "rsi", "位置": "brk" }, csK = ((window.JSQ_ENV || {}).contract_stats || {})[statKey(sym)] || {};
  const iL = env ? csK[`ind|${env.bull ? "bull" : "bear"}|long`] : null, iS = env ? csK[`ind|${env.bull ? "bull" : "bear"}|short`] : null;
  const su = (x) => x ? `${x.u >= 0 ? "+" : "−"}${Math.abs(x.u).toFixed(1)}U` : "—";
  const indNote = (k) => { const c = IND[k]; if (!c || !iL || !iS || !iL[c] || !iS[c]) return ""; return `<small class="ind-bt">历史上：它转多时做多每次 ${su(iL[c])}，转空时做空每次 ${su(iS[c])}</small>`; };
  $("cardTech").innerHTML = T.items.map((x) => `<li><span class="lean ${x.lean === "多" ? "up" : x.lean === "空" ? "down" : "flat"}">${x.lean}</span><b>${x.k}</b>${esc(x.txt)}${indNote(x.k)}</li>`).join("") +
    (iL && iS ? `<li class="ind-sum">${env.w50 ? (env.bull ? "比特币在50日线上方" : "比特币在50日线下方") : env.bull ? "牛市" : "熊市"}里的历史成绩（按100U开5倍算）。` +
      (Math.max(...Object.values(iL).map((x) => x.u)) < 1 && Math.max(...Object.values(iS).map((x) => x.u)) < 1 ? "现在这种行情，照这些指标做多做空都不赚，只当参考。" : `现在这种行情只有做${(iL.tech || iL.brk).u >= (iS.tech || iS.brk).u ? "多" : "空"}那一边赚钱。`) + `</li>` : "");
  // 结论
  let dir, cls, why, side = 0, noPlan = "", planAt = 0;
  const leanTxt = `技术面${T.lean}（${T.items.filter((x) => x.lean === "多").length}项偏多、${T.items.filter((x) => x.lean === "空").length}项偏空）`;
  const stL = env ? statFor(sym, env.bull, "long") : null, stS = env ? statFor(sym, env.bull, "short") : null;
  const gL = grade(stL), gS = grade(stS), envWord = env ? (env.w50 ? (env.bull ? "偏多行情" : "偏空行情") : env.bull ? "牛市" : "熊市") : "";
  const ok = (x) => x === "edge" || x === "unstable";
  const H = fmt(V.H, V.dp), Lw = fmt(V.L, V.dp), dayW = tf === "1d" ? "20日" : V.sess ? "最近一个交易日（7根交易时段小时线）" : "24小时";
  if (!env) { dir = T.lean === "多空分歧" ? "看不清" : `技术面${T.lean}`; cls = "flat"; why = `大方向还没算出来。${leanTxt}。`; side = T.lean === "偏多" ? 1 : T.lean === "偏空" ? -1 : 0; }
  else if (gL === "none" && gS === "none") {
    dir = "还没验证过，不做"; cls = "flat"; side = 0; noPlan = "还没验证过，所以不给进场价。";
    why = `大方向：${env.what}。${leanTxt}。<b>这个品种还没用历史数据验证过</b>，下面的指标只是描述现在的样子，不能当开单依据。`;
  } else if (["flat", "lose"].includes(gL) && ["flat", "lose"].includes(gS)) {
    dir = "不做"; cls = "flat"; side = 0; noPlan = "历史上不赚，所以不给进场价。";
    why = `${env.what}，按${envWord}对待。但这类品种在这种环境里，突破做多平均每笔${stL.s.avg > 0 ? "只" : ""}${rTxt(stL.s.avg)}、跌破做空${stS.s.avg > 0 ? "只" : ""}${rTxt(stS.s.avg)}，用这套短线规则做不出优势。`;
  } else if (T.lean !== "多空分歧") {
    const up = T.lean === "偏多", g1 = up ? gL : gS, st = up ? stL : stS, w = up ? "做多" : "做空";
    side = up ? 1 : -1;
    const head = `${env.what}，按${envWord}对待。`;
    if (g1 === "edge") { dir = `可以${w}`; cls = up ? "up" : "down"; why = head + `回测里这种环境${w}前后两段都赚钱。`; }
    else if (g1 === "unstable") { dir = `可以${w}（轻仓）`; cls = up ? "up" : "down"; why = head + `回测${w}整体赚钱，但时灵时不灵：${halfTxt(st.s, st.key)}。`; }
    else if (g1 === "few" && !up && env.bull && st.key.startsWith("sym_")) { dir = "别做空"; cls = "warn"; side = 0; noPlan = "牛市不做空，不给参考价位。"; why = head + `这只自己的样本太少（${st.s.n}笔）；但牛市里做空突破，所有回测过的分组都是亏的，这只也别做空。` + symNote(st); }
    else if (g1 === "few") { side = 0; noPlan = "回测样本太少，不给价位。";
      if (st.s.avg < 0) { dir = "不做"; cls = "flat"; why = head + `这种环境${w}回测样本不多（${st.s.n}笔），而且是亏的（平均每笔${rTxt(st.s.avg)}）。` + symNote(st); }
      else { dir = "先不做（历史数据太少）"; cls = "flat"; why = head + `历史上这种情况${w}只出现过${st.s.n}次，太少，算不准，先不做。` + symNote(st); } }
    else {
      const avoid = g1 === "lose" ? `回测里这种环境${w}是亏的（平均每笔${rTxt(st.s.avg)}）` : `回测里这种环境${w}基本不赚（平均每笔${rTxt(st.s.avg)}，扣完手续费白忙）`;
      side = 0; noPlan = "回测不支持这个方向，不给参考价位。";
      if (!up && env.bull) { dir = "别做空，等回调结束"; cls = "warn"; why = head + avoid + (ok(gL) ? "。等短线重新转强再做多。" : "。"); }
      else { dir = up ? "不追多" : "不追空"; cls = "warn"; why = head + avoid + "。"; }
    }
  } else {
    const head = `${env.what}，按${envWord}对待。`;
    if (ok(gL) && ok(gS)) { dir = "等方向出来"; cls = "flat"; side = 0; why = head + `站上${dayW}最高点 ${H} 做多、跌破最低点 ${Lw} 做空，回测这种环境两边都赚。`; }
    else if (ok(gL)) { dir = "等突破再做多"; cls = "warn"; side = 1; planAt = V.H; why = head + `等价格站上${dayW}最高点 ${H} 再做多${gS === "lose" || gS === "flat" ? "，不做空（回测这种环境做空不赚）" : ""}。`; }
    else if (ok(gS)) { dir = "等跌破再做空"; cls = "warn"; side = -1; planAt = V.L; why = head + `等价格跌破${dayW}最低点 ${Lw} 再做空${gL === "lose" || gL === "flat" ? "，不做多（回测这种环境做多不赚）" : ""}。`; }
    else { dir = "先不做"; cls = "flat"; side = 0; why = head + (gL === "few" || gS === "few" ? "历史上这种情况出现得太少，做多做空都算不出优势，先不做。" + symNote(stL || stS) : "历史上这种时候做多做空都不赚，先不做。");
      { const dm = DMA[sym], lv = dm && (env.m50 ? dm.ma50 : dm.ma200), ln = env.m50 ? "50日线" : "200日线"; if (dm && U.groupOfSym(sym) === "metal" && !env.bull && isFinite(lv)) why += ` <b>等什么</b>：收盘站上${ln} <b>${fmt(lv, V.dp)}</b>（比现在高 ${pabs(lv / V.last - 1)}）以后，才按"突破就做多"找机会。`; } }
  }
  // 有回测依据的方向：结论只看回测用的那个突破信号，不看技术指标偏多偏空（和"今天能做什么"清单同一套算法）
  let stpOv = 0;
  if (env && !dipMode && (ok(gL) || ok(gS))) {
    const sd = ok(gL) ? 1 : -1, b = brk(sym, sd), w = sd === 1 ? "做多" : "做空", bw = sd === 1 ? "突破" : "跌破", gg = sd === 1 ? gL : gS, st = sd === 1 ? stL : stS;
    const head = `${env.what}，按${envWord}对待。`, light = gg === "unstable" ? "（轻仓）" : "", other = `这时候不${sd === 1 ? "做空" : "做多"}（历史上不赚）`;
    const note = gg === "unstable" ? `历史上这样${w}整体赚钱，但时灵时不灵，所以轻仓：${halfTxt(st.s, st.key)}。` : `历史上这样${w}一直是赚钱的。`;
    const tOK = techOK(sym, env, sd); if (tOK) needD1(sym).then(() => { if (!D1seen[sym] && D1[sym]) { D1seen[sym] = 1; if (window.JSQ.state.sym === sym) renderCard(true); } }).catch(() => {});
    const tk = tOK ? sigEngine(sym, 1, "tech") : null, tS = tOK ? (csK["ind|bull|long"] || {}).tech : null;
    const tNote = tS ? `回测：技术面翻多做多平均每次 ${su(tS)}（${tS.n}笔，前后两段 ${su({ u: tS.h1 })}/${su({ u: tS.h2 })}）。` : "";
    if (!b) { dir = "等小时线载入…"; cls = "flat"; side = 0; why = head; noPlan = "正在取小时线。"; }
    else if (tk && tk.stage === "fresh" && b.stage !== "fresh") { dir = "可以做多（技术面刚翻多）"; cls = "up"; side = 1; planAt = 0; stpOv = tk.stop0;
      why = head + `${agoTxt(tk)}几个指标一起转多了（均线、MACD、RSI、位置、日线里偏多的比偏空的多2项以上），这也是验证过的进场信号。` + tNote + other + "。"; }
    else if (b.stage === "fresh") { dir = `可以${w}${light}`; cls = sd === 1 ? "up" : "down"; side = sd; planAt = 0; stpOv = b.stop0;
      why = head + `${agoTxt(b)}${bw}了${b.win}${sd === 1 ? "最高" : "最低"}点，进场条件到了。` + note + other + "。"; }
    else if (b.stage === "open") { dir = `信号已经出过，现在不追`; cls = "flat"; side = 0;
      why = head + `${agoTxt(b)}出过${w}信号（${bw} ${fmt(b.E, V.dp)}）。回测只算了在信号那一小时进场，晚进没验证过，所以现在不追。<b>下一次机会</b>：价格${sd === 1 ? "跌回" : "涨回"} <b>${fmt(b.st, V.dp)}</b> ${sd === 1 ? "以下" : "以上"}（或小时趋势掉头）这一波就算结束，之后再${bw}那时的${b.win}${sd === 1 ? "最高" : "最低"}点才是下一次信号。`;
      noPlan = `现在不新开仓。已经在里面的：止损放 <b>${fmt(b.st, V.dp)}</b>` + (b.armed ? `（已经赚够一倍止损的钱，止损跟着最近3天${sd === 1 ? "最低" : "最高"}点往${sd === 1 ? "上" : "下"}挪）。` : `，${sd === 1 ? "涨" : "跌"}到 ${fmt(b.E + sd * b.Rk, V.dp)} 再挪到开仓价。`); }
    else if (b.crossed) { const pos = sd === 1 ? "上方" : "下方", closed = b.stock && !inSession();
      dir = `已经${sd === 1 ? "涨过" : "跌破"} ${fmt(b.level, V.dp)}：等${b.when.txt}收盘确认`; cls = "warn"; side = sd; planAt = null; stpOv = b.stopIf;
      why = head + `现价 ${fmt(b.lp, V.dp)} 已经在${b.win}${sd === 1 ? "最高" : "最低"}点 <b>${fmt(b.level, V.dp)}</b> ${pos}。` +
        (closed ? `现在是美股盘前/盘后/夜盘${nyInfo(Date.now()).wd === "Sat" || nyInfo(Date.now()).wd === "Sun" ? "（周末）" : ""}，币安合约照样在${sd === 1 ? "涨" : "跌"}，但这时候${sd === 1 ? "涨过" : "跌破"}的不算数：查了今年币安124只美股合约，休市时先${sd === 1 ? "涨过" : "跌破"}的，<b>4成多到美股开盘后站不住</b>，这些单子平均每笔亏0.6倍止损、10笔里只赚1笔；周末${sd === 1 ? "涨过" : "跌破"}的最不靠谱。所以要等 <b>${b.when.txt}</b>（美股开盘后第一根1小时线收盘）还在 ${fmt(b.level, V.dp)} ${pos}，才算${w}信号。等确认的代价是进场价平均差1%左右，换来躲掉一大半假突破。止损不分时段，24小时都有效。`
                : `要等 <b>${b.when.txt}</b> 这根1小时线收盘还在 ${fmt(b.level, V.dp)} ${pos}，才算${w}信号（盘中冲过去又收回来的不算）。`) +
        (b.trendOK ? "" : `同时短期走势要先转${sd === 1 ? "强" : "弱"}。`) + `${other}。` + note; }
    else { dir = `${b.near ? "快到了：" : ""}等${sd === 1 ? "涨过" : "跌破"} ${fmt(b.level, V.dp)} 再${w}${light}`; cls = "warn"; side = sd; planAt = b.level; stpOv = b.stopIf;
      why = head + `等价格${sd === 1 ? "涨过" : "跌破"}${b.win}${sd === 1 ? "最高" : "最低"}点 <b>${fmt(b.level, V.dp)}</b>（还差 ${pabs(b.dist / b.lp)}，按1小时K线收盘算）再${w}` +
        (b.trendOK ? "" : `，同时短期走势要先转${sd === 1 ? "强" : "弱"}`) + `；${other}。` + note; }
    if (tk && tk.stage === "flat") why += ` <b>另一种进场</b>：等几个指标一起转多。`;
    else if (tk && tk.stage === "open" && b.stage !== "fresh") why += ` 指标${agoTxt(tk)}也出过转多信号，同样不追。`;
  }
  let dipPlan = "";
  if (dipMode) {
    const d = dipState(sym, V, "bear");
    if (d) { dir = d.dir; cls = d.cls; why = d.why; side = 0; dipPlan = d.plan || ""; noPlan = d.plan ? "" : "现在不是买点，所以不给进场价。"; }
  } else if (bullDip) {
    const d = dipState(sym, V, "bull");
    if (d && d.cls === "up") { dir = d.dir; cls = d.cls; why = d.why; side = 0; dipPlan = d.plan; }
    else if (d && d.dir.startsWith("等企稳")) why += `<br>另外：${d.why}`;
  }
  setDir(dir, cls);
  { // 已经有仓位：老单按开仓时那套规则管，这里的信号是给没仓位时开新单的（用户 2026-11-12 问：AMD 多单说576止盈，卡上又说涨到568做多）
    const P0 = loadPos(sym), pe = numv(P0.E), ps = +P0.side || 1;
    if (pe > 0) why += ` <span class="pos-note"><b>你已经有${ps === 1 ? "多" : "空"}单（开仓价 ${fmt(pe, V.dp)}）</b>：老单照下面"我已经有仓位"里的计划管，${side && side !== ps ? "这里的新信号方向和你相反，先守你自己的止损。" : "不因为这里的新信号改止盈、也不加仓；这里说的价位是给没有仓位时开新单用的。"}</span>`;
  }
  $("cardWhy").innerHTML = why + (env ? `<span class="src">（${esc(env.src)}）</span>` : "");
  // 价位
  $("cardPlan").innerHTML = dipPlan ? dipPlan : side ? plan(V, side, tf, planAt && isFinite(planAt) && side * (planAt - V.last) > 0 ? planAt : 0, sym, env, stpOv) : (noPlan || "现在不做，所以不给进场价。");
  // 这单开多大：止损打到最多亏本金的0.5%（账户回测 research/risk_bt.py）
  if (PLANNUM && (side || dipPlan)) {
    const acct = numv(($("posAcct") || {}).value) || numv(localStorage.getItem("jsq.acct")) || 3200, rk = Math.abs(PLANNUM.stop / PLANNUM.E0 - 1), lose = acct * 0.005;
    if (rk > 0) { const not = Math.min(lose / rk, acct * 0.8);
      $("cardPlan").innerHTML += `<br><b>这单开多大</b>：止损打到最多亏 <b>${lose.toFixed(0)}U</b>（本金 ${acct.toFixed(0)}U 的0.5%）→ 满仓持仓价值约 <b>${not.toFixed(0)}U</b>（开5倍就是 ${(not / 5).toFixed(0)}U 保证金）。止损离得远就少开，离得近可以多开。`;
      // 赚了再加（research/add_winners_bt.py，2026-11-13 起）：做多 开一份→1R 再加一份、全部止损挪到第一笔开仓价；币可在 2R 再加；空单不加；"大跌后止跌"一次性开
      const sk = statKey(sym), sd2 = PLANNUM.side || side || 1, E0 = PLANNUM.E0, Rr = Math.abs(E0 - PLANNUM.stop), F = (x) => fmt(x, V.dp);
      if (!dipPlan && (sk === "crypto" || (sk === "stock_main" && env && env.bull && sd2 === 1))) {
        const a1 = E0 + sd2 * Rr, a2 = E0 + sd2 * 2 * Rr, mv = sd2 === 1 ? "涨" : "跌";
        const one = sd2 === 1, PBN = sk === "crypto" ? ["+1.5", "+3.2"] : ["+5.6", "+8.3"];
        $("cardPlan").innerHTML += one ? `<br><b>赚了再加</b>：① 按上面开一份，止损 ${F(PLANNUM.stop)}；② ${mv}到 <b>${F(a1)}</b>（1倍止损距离）再加一份同样大的，加完<b>全部止损挪到 ${F(E0)}</b>，加了仓也亏不了；` +
          (sk === "crypto" ? `③ 再${mv}到 <b>${F(a2)}</b> 可以再加一份，全部止损挪到 ${F(a1)}；` : `③ 股票只加这一次（隔夜跳空，加两次最差一笔大很多）；`) +
          `之后止损跟着最近3天最低点挪，一起出场。没到 ${F(a1)} 就不加，亏着的仓位永远不加。` +
          `<br><span class="plan-bt">回测（5年顺着走势开的多单，research/add_winners_bt.py）：不加每笔 ${PBN[0]}U，涨到1倍再加一份 ${PBN[1]}U，前后两段都更好；亏着加（拉均价）更差。</span>`
          : `<br><b>加仓</b>：空单不加（回测里空单加仓平均反而变差）。`;
      } else if (sk === "XAUUSD" || sk === "XAGUSD") $("cardPlan").innerHTML += `<br><b>赚了再加</b>：涨到1倍止损距离再加一份同样大的，全部止损挪到第一笔开仓价；金银只加这一次（回测：不加每笔 +1.6U，加一次 +2.9U）。`;
      else if (dipPlan) $("cardPlan").innerHTML += `<br>这类单子一次性开，不加仓（有固定止盈，加仓没验证过）。`;
    }
  }
  // 历史
  const hl = [];
  if (dipMode) {
    hl.push("熊市里回调企稳做多（纳指前一天在跌）：90次，每次（100U×5倍）平均 +6.2U；纳指前一天在涨时进：19次平均 −14.7U（AMD/美光/戴尔 2021-11~2026-10）");
    hl.push(histLine(stS, "熊市里跌破做空"));
  } else if (env) {
    hl.push(histLine(stL, `${envWord}里突破做多`));
    hl.push(histLine(stS, `${envWord}里跌破做空`));
  }
  $("cardHist").innerHTML = hl.filter(Boolean).map(esc).join("<br>");
  $("cardVol").innerHTML = volText(sym, V);
  // 提醒
  const warns = [];
  if (g === "stock" && usMarketClosed()) warns.push("美股现在休市：合约价开盘时可能跳空，止损可能滑点。");
  if (g === "stock") {
    const ed = ((window.JSQ_ENV || {}).earnings || {})[sym.replace("USDT", "")];
    if (ed) { const days = Math.round((new Date(ed + "T00:00:00Z") - new Date()) / 864e5); if (days >= -1 && days <= 10) warns.push(`${ed} 出财报（${days <= 0 ? "就在这两天" : days + "天后"}），前后容易跳空。`); }
    const u = usNow(); if (u && u.stopDist < 0.05) warns.push(`纳指离认错线只差 ${pabs(u.stopDist)}，到了就按长熊处理。`);
    // 熊市里纳指大涨：回测（^NDX 2000年起）熊市里单日涨≥2%之后5天平均 −0.75%，20天内站回200日线的只有约1/6
    const LQ = window.JSQ_LIVE_US, UQ = ((window.JSQ_ENV || {}).live || {}).us;
    if (u && !u.bull && LQ && LQ.QQQ && UQ && UQ.QQQ && LQ.QQQ / UQ.QQQ.close - 1 >= 0.02)
      warns.push(`纳指今天涨了 ${pct(LQ.QQQ / UQ.QQQ.close - 1)}，但还在200日线下方：2000年以来熊市里纳指单日涨2%以上共283次，之后5天平均跌0.75%，20天内站回200日线的只有约六分之一——大涨日别追，等站回200日线再按牛市规则做。`);
  }
  if (["SOXLUSDT", "TQQQUSDT", "SQQQUSDT"].includes(sym)) warns.push("这是三倍杠杆ETF，波动是普通股票的三倍。");
  warns.push("每笔止损打到最多亏本金的0.5%；同时最多拿：币4个、股票3个、金银2个。");
  $("cardWarn").textContent = warns.join(" ");
  $("ckLong").hidden = !(side === 1 || (dipPlan && PLANNUM)); $("ckShort").hidden = side !== -1;
  const okL = dipMode || ok(gL) || (bullDip && dipPlan), okS = ok(gS);
  renderPos(sym, V, env, g, dipMode, +(($("posSide") || {}).value || 1) === 1 ? okL : okS);
}

// ================================================================ 选品种
function openPicker() { $("picker").hidden = false; $("pickQ").value = ""; renderPick(); setTimeout(() => $("pickQ").focus(), 50); }
function closePicker() { $("picker").hidden = true; }
let pickGroup = "fav";
function renderPick() {
  const q = $("pickQ").value.trim().toLowerCase(), favs = U.favs(), J = window.JSQ;
  $("pickTabs").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.g === pickGroup)));
  let list = q ? U.all.filter((s) => s.toLowerCase().includes(q) || (U.names[s] || "").toLowerCase().includes(q))
    : pickGroup === "fav" ? favs : pickGroup === "metal" ? U.METALS : pickGroup === "crypto" ? U.CRYPTO : U.STOCKS;
  $("pickList").innerHTML = list.map((s) => `<div class="pick-row${J && J.state.sym === s ? " on" : ""}"><button type="button" class="pick-go" data-s="${s}"><b>${esc(U.names[s])}</b><small>${s.replace("USDT", "")}</small></button><button type="button" class="pick-star" data-s="${s}" aria-label="自选">${favs.includes(s) ? "★" : "☆"}</button></div>`).join("") || `<p class="note">没找到。</p>`;
}
function initPicker() {
  $("pickOpen").addEventListener("click", openPicker);
  $("pickClose").addEventListener("click", closePicker);
  $("picker").addEventListener("click", (e) => { if (e.target === $("picker")) closePicker(); });
  $("pickQ").addEventListener("input", renderPick);
  $("pickTabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { pickGroup = b.dataset.g; $("pickQ").value = ""; renderPick(); }));
  $("pickList").addEventListener("click", (e) => {
    const go = e.target.closest(".pick-go"), star = e.target.closest(".pick-star");
    if (star) { const s = star.dataset.s, f = U.favs(); const i = f.indexOf(s); if (i >= 0) { if (f.length > 1) f.splice(i, 1); } else f.push(s); U.saveFavs(f); window.JSQ.setFavs(f); renderPick(); }
    else if (go) { closePicker(); window.JSQ.select(go.dataset.s); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("picker").hidden) closePicker(); });
}

// ================================================================ 正股：一眼看懂
function renderBrief() {
  const E = window.JSQ_ENV; if (!E) return;
  const a = E.a.today, AL = window.JSQ_LIVE_A, t = AL ? AL.temp : a.temp, reg = AL ? AL.regime : a.regime, b = band(t);
  let aDo;
  if (reg === "熊市") aDo = b === "冰点" ? "可以分批买" : b === "偏冷" ? "快到冰点，可以小仓开始分批" : b === "中性" ? "少动，等温度跌到20以下再分批买" : "别追：熊市里突然变热多数是反弹陷阱";
  else aDo = (b === "冰点" || b === "偏冷") ? "回调可以买（优先上升趋势里回踩20日线的票）" : b === "中性" ? "正常拿着" : b === "偏热" ? "别追高" : "别追，过热之后60天平均是跌的";
  const u = usNow();
  let uDo = "—", uWhat = "";
  if (u) {
    uWhat = `纳指离200日线 ${pct(u.vs)}，标普 ${pct(u.spxVs)}`;
    const SU = (window.JSQ_ENV || {}).stocks_us;
    if (u.bull) uDo = SU && SU.picks ? `牛市：正股按名单买（现在 ${SU.picks.length} 只${SU.picks.length ? "：" + SU.picks.join("、") : ""}），跌了30%以上的不抄；合约不做空` : "牛市：正股正常拿着；合约不做空";
    else if (u.spxVs > 0) uDo = `科技股在调整、标普还没破：正股可以分批买、留足现金；合约少做`;
    else uDo = `大盘也破了200日线：分批、留现金；纳指跌到 ${fmt(u.stop, 0)}（认错线）就减仓`;
  }
  const v20 = AL && AL.ew_vs20 != null ? AL.ew_vs20 : a.ew_vs_ma20;
  aDo += v20 == null ? "" : v20 < 0 ? "；小市值组合刹车中（全A等权在20日线下，站回再买）" : "；小市值30只组合拿着（全A等权在20日线上），每月初换";
  const mt = window.JSQ_MAIN_TOP || (a.top_ind || []);
  const rows = [
    ["A股", `${reg} · ${b}（${Math.round(t)}）`, aDo, reg === "牛市" ? "good" : "warn"],
    ["美股", u ? (u.bull ? "牛市" : "熊市") : "—", uDo + (uWhat ? `。${uWhat}` : ""), u && u.bull ? "good" : "warn"],
    ["主线", mt.slice(0, 3).map((x) => x.name).join("、") || "—", "成交占比比平时放大最多的行业（只是资金去向，不是买卖信号）", "flat"],
  ];
  $("briefBody").innerHTML = rows.map(([k, s, d, c]) => `<div class="brief-row"><span class="brief-k">${k}</span><div><b class="chip ${c}">${esc(s)}</b><p>${esc(d)}</p></div></div>`).join("");
  $("briefSub").textContent = AL ? "盘中实时" : `${+a.date.slice(5, 7)}月${+a.date.slice(8, 10)}日收盘`;
}

// ================================================================ 启动
function init() {
  initTabs(); initPicker(); initPos();
  $("ckLong").addEventListener("click", () => { $("foldCalc").open = true; const b = $("use24L"); if (b) { b.click(); $("foldCalc").scrollIntoView({ behavior: "smooth", block: "start" }); } });
  $("ckShort").addEventListener("click", () => { $("foldCalc").open = true; const b = $("use24S"); if (b) { b.click(); $("foldCalc").scrollIntoView({ behavior: "smooth", block: "start" }); } });
  document.addEventListener("jsq-view", () => renderCard(false));
  document.addEventListener("jsq-env-ready", () => { mergePerps(); renderBar(); renderCard(true); renderBrief(); renderEP(); scanAll(true); renderPosList(); renderLedger(); });
  document.addEventListener("jsq-live", () => { renderBar(); renderCard(false); renderBrief(); renderEP(); });
  const refresh = async () => { await Promise.allSettled(["XAUUSDT", "XAGUSDT", "BTCUSDT"].map(needDMA)); renderBar(); renderCard(true); };
  refresh(); setInterval(refresh, 5 * 60e3);
  renderBar();
}
init();
})();
