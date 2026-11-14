(() => {
"use strict";
// 正股页：被套了怎么办——我的正股（research/holder_bt.py、holder3_bt.py：A股2.1万次、美股1344次"离一年高点跌30%"，看之后250天）
// 数据：stocks_a.json（个股 px/dd/m60/bs/bup、etf 块、mkt60）、stocks_us.json 的 hold 块（qqq60）；大盘牛熊用 env 和盘中估算。
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pc = (x, d = 1) => x == null || !isFinite(x) ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(d) + "%";
const fp = (x) => x == null || !isFinite(x) ? "—" : x.toFixed(x < 10 ? 3 : 2);
const KEY = "jsq.mystk";
// 回测数字（250天后；"加仓" = 跌到起点的90%、80%各加1份，按原来1份算的盈亏）
const ST = {
  A: {
    good: { n: 9442, hold: "+21.7%", w: "−24.3%", f20: "48%", add: "+58.0%", aw: "−41.7%" },
    selfDn: { n: 437, hold: "+14.2%", w: "−33.3%", f20: "58%", add: "+42.8%", aw: "−73.5%" },
    mktUp: { n: 9411, hold: "+20.0%", w: "−35.7%", f20: "49%", add: "+31.2%", aw: "−80.8%" },
    worst: { n: 1857, hold: "+10.2%", w: "−39.7%", f20: "62%", add: "+20.4%", aw: "−94.2%" },
  },
  US: {
    good: { n: 633, hold: "+21.8%", w: "−24.5%", f20: "36%", add: "+42.5%", aw: "−41.4%" },
    selfDn: null,
    mktUp: { n: 384, hold: "+33.9%", w: "−37.1%", f20: "46%", add: "+71.3%", aw: "−86.2%" },
    worst: { n: 299, hold: "+17.0%", w: "−39.0%", f20: "46%", add: "+31.8%", aw: "−89.7%" },
  },
};
const loadQ = (url) => new Promise((res, rej) => { const s = document.createElement("script"); s.src = url; s.charset = "gbk"; s.async = true;
  const t = setTimeout(() => { s.remove(); rej(new Error("timeout")); }, 8000);
  s.onload = () => { clearTimeout(t); s.remove(); res(); }; s.onerror = () => { clearTimeout(t); s.remove(); rej(new Error("load")); };
  document.head.appendChild(s); });
const take = (k) => { const v = window[k]; try { delete window[k]; } catch (e) { window[k] = undefined; } return v; };
const getJ = (u) => fetch(u + "?d=" + new Date().toISOString().slice(0, 13)).then((r) => r.ok ? r.json() : null).catch(() => null);

// 代码：sh600000 / sz002463 / 600000（自动补交易所）/ NVDA
function norm(x) {
  x = String(x || "").trim();
  if (/^(sh|sz)\d{6}$/i.test(x)) return x.toLowerCase();
  if (/^\d{6}$/.test(x)) return (/^[569]/.test(x) ? "sh" : "sz") + x;
  if (/^[A-Za-z][A-Za-z.\-]{0,9}$/.test(x)) return x.toUpperCase();
  return null;
}
function parse(text) {           // "sz002463 95 2, sh601138 50, NVDA"：代码 [成本] [份数]
  const out = [];
  for (const part of String(text).split(/[,，;；\n]+/)) {
    const tk = part.trim().split(/\s+/).filter(Boolean); if (!tk.length) continue;
    const c = norm(tk[0]); if (!c) continue;
    const cost = tk[1] != null && isFinite(+tk[1]) && +tk[1] > 0 ? +tk[1] : null;
    const u = tk[2] != null && isFinite(+tk[2]) && +tk[2] > 0 ? Math.min(9, Math.round(+tk[2])) : 1;
    out.push({ c, cost, u });
  }
  return out;
}
function load() {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); if (Array.isArray(v) && v.length) return v; } catch (e) {}
  let t = ["sz002463", "sh601138", "sh512760"];
  try { const v = JSON.parse(localStorage.getItem("jsq.techhold") || "null"); if (Array.isArray(v) && v.length) t = v; } catch (e) {}
  return t.map((c) => ({ c, cost: null, u: 1 }));
}
const fmtList = (L) => L.map((h) => [h.c, h.cost != null ? h.cost : (h.u > 1 ? 0 : null), h.u > 1 ? h.u : null].filter((x) => x != null).join(" ")).join(", ");

let A = null, U = null;
async function data() {
  if (!A || !U) {
    const [a, u] = await Promise.all([getJ("stocks_a.json"), getJ("stocks_us.json")]);
    const idx = (d, F) => { const m = {}; if (d && d.rows) for (const r of d.rows) m[r[0]] = Object.fromEntries(F.map((k, i) => [k, r[i]])); return m; };
    A = a ? { s: idx(a, a.fields), e: a.etf ? idx(a.etf, a.etf.fields) : {}, mkt60: a.mkt60, date: a.date } : { s: {}, e: {} };
    U = u && u.hold ? { s: idx(u.hold, u.hold.fields), qqq60: u.hold.qqq60, date: u.hold.date } : { s: {} };
  }
}
async function quotes(list) {     // 腾讯简版行情 s_：f[3] 现价；美股 s_usNVDA
  const syms = list.map((c) => "s_" + (/^(sh|sz)/.test(c) ? c : "us" + c.replace(/[.\-]/g, "")));
  const out = {};
  try {
    await loadQ("https://qt.gtimg.cn/q=" + syms.join(","));
    list.forEach((c, i) => { const v = take("v_" + syms[i]); if (typeof v === "string") { const f = v.split("~"); if (+f[3] > 0) out[c] = { px: +f[3], name: f[1] }; } });
  } catch (e) {}
  return out;
}
function regime(isUS) {           // 大盘在200日线下？A股 = 全A等权，美股 = 纳指100
  const E = window.JSQ_ENV; if (!E) return null;
  if (!isUS) {
    const AL = window.JSQ_LIVE_A, v = AL && AL.ew_vs != null ? AL.ew_vs : E.a.today.ew_vs_ma200;
    return { down: v < 0, vs: v, name: "全A等权", live: !!(AL && AL.ew_vs != null) };
  }
  const L = window.JSQ_LIVE_US, UL = E.live && E.live.us;
  if (L && L.QQQ && UL && UL.QQQ && UL.QQQ.sum199) { const v = L.QQQ / ((UL.QQQ.sum199 + L.QQQ) / 200) - 1; return { down: v < 0, vs: v, name: "纳指100", live: true }; }
  return { down: E.us.today.ndx_vs < 0, vs: E.us.today.ndx_vs, name: "纳指100", live: false };
}

// 卖在高处（research/ashare_top5_bt.py，完整记账、收盘确认第二天开盘成交）：比60日线高40%以上卖当时股数的一半，收盘跌回60日线第二天开盘买回；近5年+2.6个点、2016~2021+2.0个点（比一直持有）
function sellHigh(row, k) {
  if (row.v60 == null || !isFinite(row.v60)) return `<b>卖在高处</b>：没有60日线数据。`;
  const ma = row.px / (1 + row.v60), p = row.px * k, v = p / ma - 1, tgt = ma * 1.4;
  return v >= 0.4
    ? `<b>卖在高处</b>：现在比60日线（${fp(ma)}）高 ${pc(v)}，<b>收盘还在这上面，第二天开盘卖一半</b>；以后收盘跌回60日线，第二天开盘买回。`
    : `<b>卖在高处</b>：收盘比60日线高40%（现在约 <b>${fp(tgt)}</b>，60日线 ${fp(ma)} 每天在变）就第二天开盘卖一半，收盘跌回60日线再买回。现在比60日线 ${pc(v)}。`;
}

function judge(h, row, live, isUS, isETF) {
  const k = live && row.px && Math.abs(live / row.px - 1) < 0.4 ? live / row.px : 1, p = row.px * k;
  const hi = row.px / (1 + row.dd), dd = p / hi - 1;
  const R = regime(isUS), mk = isUS ? U.qqq60 : A.mkt60;
  const rel = row.m60 != null && mk != null ? ((1 + row.m60) * k - 1) - mk : null;
  const pnl = h.cost ? p / h.cost - 1 : null;
  const o = { p, hi, dd, rel, pnl, R, lines: [], chips: [] };
  const line30 = hi * 0.7, add1 = hi * 0.63, add2 = hi * 0.56;
  if (dd > -0.3) {
    o.chips.push(["flat", `离一年高点 ${pc(dd)}`]);
    o.state = "none";
    o.lines.push(sellHigh(row, k));
    o.lines.push(`<b>跌了加不加</b>：还不算被套（跌到 <b>${fp(line30)}</b> 才算跌了30%），这之前别因为"跌了便宜"就加。`);
    return o;
  }
  const mktDown = R ? R.down : null, self = rel != null && rel <= -0.2;
  const good = mktDown === true && !self;
  const S = ST[isUS ? "US" : "A"][good ? "good" : (mktDown ? "selfDn" : (self ? "worst" : "mktUp"))];
  const cap = good ? 3 : 1;
  o.state = good ? "good" : "bad"; o.cap = cap;
  o.chips.push([good ? "good" : "bad", good ? "可以按价位加" : "不加"]);
  o.chips.push(["flat", `离一年高点 ${pc(dd)}`]);
  const why = [];
  if (R) why.push(`${R.name}${R.down ? "在200日线下" : "在200日线上"}（${pc(R.vs)}）`);
  if (rel != null) why.push(self ? `它60天比大盘多跌了 ${pc(-rel).replace("+", "")}（是它自己出事）` : `它60天比大盘${rel < 0 ? "多跌" : "少跌"} ${pc(Math.abs(rel)).replace("+", "")}（跟着大盘跌）`);
  o.lines.push(`<b>状态</b>：被套（一年高点 ${fp(hi)}）；${why.join("，")}。`);
  // 跌了加不加
  if (good) {
    const lv = [[add1, "第1份"], [add2, "第2份"]].map(([x, nm]) => `${nm} <b>${fp(x)}</b>${p <= x ? "（已到）" : ""}`).join("，");
    const left = Math.max(0, cap - (h.u || 1)), hit = (p <= add1 ? 1 : 0) + (p <= add2 ? 1 : 0);
    const now = left === 0 ? "<b>你已经加满了，再跌也不加</b>" : hit && (h.u || 1) - 1 < hit ? `你现在 ${h.u || 1} 份，<b>已经到了 ${Math.min(hit, left)} 个价位，还没加的现在可以加</b>，再跌也最多到3份` : `你现在 ${h.u || 1} 份，还能加 ${left} 份`;
    o.lines.push(`<b>跌了加不加</b>：大家一起跌的这种，跌到一年高点的63%、56%各加1份：${lv}。${now}。`);
  } else {
    o.lines.push(`<b>跌了加不加</b>：<b>不加</b>。${mktDown === false ? "大盘还在200日线上、只有它跌了30%，" : ""}${self ? "它自己比大盘多跌这么多，" : ""}这种时候"越跌越加"最差的10%要亏掉原来那份的 ${S ? S.aw.replace("−", "") : "八九成"}，加进去的钱等于跟着一起亏。`);
  }
  // 涨了卖不卖
  let L = null, bounce = null;
  if (row.bs >= 1 && row.bup != null && isFinite(row.bup)) { L = row.px / (1 + row.bup); if (row.bs === 4 || p < L) L = Math.min(L, p); bounce = L * 1.15; }
  const over = (h.u || 1) - cap;
  // 反弹还是反转：第一波反弹那天 7 条对上几条（只有A股个股有），以及"涨到低点1.3倍"这条确认线
  const RS = [[2, "27%", "55%", "26%", "58%"], [3, "35%", "47%", "28%", "57%"], [4, "39%", "44%", "31%", "56%"], [5, "41%", "40%", "32%", "55%"], [7, "54%", "29%", "41%", "47%"]];
  if (L) {
    const up = p / L - 1, conf = L * 1.3;
    let t = `<b>反弹还是反转</b>：现在比这轮低点 ${fp(L)} ${pc(up)}。`;
    if (row.bs >= 2 && row.rsc != null && row.rsc >= 0) {
      const b = RS.find((x) => row.rsc <= x[0]);
      t += `反弹起来那天7条迹象对上 <b>${row.rsc} 条</b>，同样的情况 ${b[1]} 后来涨到低点的1.5倍、${b[2]} 又跌破低点（老数据 ${b[3]} / ${b[4]}）。`;
    }
    t += p >= conf ? `已经过了反转确认线 <b>${fp(conf)}</b>（低点×1.3），过线后只有三成左右再破低点。` : `涨过 <b>${fp(conf)}</b>（低点×1.3）才算反转，之前都只是反弹。`;
    o.lines.push(t);
  }
  const bTxt = bounce ? (p >= bounce ? `现在已经过了第一波反弹价 ${fp(bounce)}（这轮低点 ${fp(L)} 涨15%）` : `第一波反弹价是 <b>${fp(bounce)}</b>（这轮低点 ${fp(L)} 涨15%）`) : "";
  if (over > 0) {
    o.lines.push(`<b>涨了卖不卖</b>：你有 ${h.u} 份，超过这种状态的上限 ${cap} 份。${bTxt ? bTxt + "，" : ""}${bounce && p >= bounce ? "<b>现在就把多出来的 " + over + " 份卖掉</b>" : "<b>反弹到这里把多出来的 " + over + " 份卖掉</b>"}，剩下的拿着。不是看空它，是把仓位降到扛得住的大小。`);
  } else {
    o.lines.push(`<b>涨了卖不卖</b>：<b>反弹不卖，拿着</b>。${bTxt ? bTxt + "。" : ""}"反弹卖、回落接"试了12种，平均都不比拿着强。`);
  }
  if (row.v60 != null) o.lines.push(sellHigh(row, k));
  if (S) o.lines.push(`<span class="note">像这样的 ${S.n.toLocaleString()} 次：死扛250天后平均 ${S.hold}，最差10% ${S.w}，${S.f20} 之后又再跌了20%以上；按规则越跌越加平均 ${S.add}，最差10% ${S.aw}（按原来1份算）。${isETF ? "ETF 套用的是个股的规律。" : ""}</span>`);
  else o.lines.push(`<span class="note">美股这种状态（大盘在200日线下、它自己多跌20%以上）近5年不到30次，没有单独的数字，按"不加"处理。</span>`);
  return o;
}

async function render() {
  const box = $("holdBody"); if (!box || !window.JSQ_ENV) return;
  await data();
  const L = load();
  const live = await quotes(L.map((h) => h.c));
  let nGood = 0, nBad = 0, nNone = 0, miss = [];
  const html = L.map((h) => {
    const isUS = !/^(sh|sz)/.test(h.c), code = isUS ? h.c : h.c.slice(2);
    const row = isUS ? U.s[h.c] : (A.s[code] || A.e[code]);
    const isETF = !isUS && !A.s[code] && !!A.e[code];
    const q = live[h.c];
    const name = (row && row.name) || (q && q.name) || h.c;
    if (!row || !row.px || row.dd == null) { miss.push(h.c); return `<div class="tk-r"><div class="tk-h"><b>${esc(name)}</b>${q ? `<span class="tk-p num">${fp(q.px)}</span>` : ""}</div><p class="note">数据里没有这只（${esc(h.c)}）：A股个股、国泰/国联安半导体ETF、科创50ETF、美股约570只有数据。</p></div>`; }
    const o = judge(h, row, q && q.px, isUS, isETF);
    if (o.state === "good") nGood++; else if (o.state === "bad") nBad++; else nNone++;
    const chips = o.chips.map(([c, t]) => `<span class="chip ${c}">${t}</span>`).join("");
    const pl = o.pnl != null ? `<span class="hd-pl ${o.pnl >= 0 ? "up" : "down"}">成本 ${fp(h.cost)} · ${pc(o.pnl)}</span>` : "";
    return `<div class="tk-r"><div class="tk-h"><b>${esc(name)}</b><span class="tk-p num">${fp(o.p)}</span></div>
      <div class="hd-c">${chips}${pl}</div>${o.lines.map((x) => `<p>${x}</p>`).join("")}</div>`;
  }).join("");
  const sum = [];
  if (nGood) sum.push(`${nGood} 只是"大家一起跌"，可以按价位加，最多3份`);
  if (nBad) sum.push(`${nBad} 只<b>不加</b>`);
  if (nNone) sum.push(`${nNone} 只还没被套到30%`);
  $("holdSum").innerHTML = sum.length ? `你的 ${L.length - miss.length} 只：${sum.join("；")}。反弹都不用急着卖，只有超过上限的份数要在反弹时卖掉。` : "";
  box.innerHTML = html;
  const ad = A.date, ud = U.date;
  $("holdNote").textContent = `收盘数据 A股 ${ad || "—"}、美股 ${ud || "—"}；现价来自腾讯行情，取不到就用收盘价。`;
}

function init() {
  if (!$("holdPanel")) return;
  const inp = $("holdCodes");
  inp.value = fmtList(load());
  $("holdSave").addEventListener("click", () => {
    const v = parse(inp.value);
    if (v.length) { localStorage.setItem(KEY, JSON.stringify(v)); inp.value = fmtList(v); render(); }
  });
  const go = () => { if (!document.getElementById("tab-stock").hidden) render(); };
  document.addEventListener("jsq-tab", go);
  if (window.JSQ_ENV) go(); else document.addEventListener("jsq-env-ready", go, { once: true });
  setInterval(go, 60e3);
}
init();
})();
