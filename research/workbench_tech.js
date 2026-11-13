(() => {
"use strict";
// 正股页：我的科技股——今天高开/低开怎么办（research/intraday_t_bt.py，20只科技股+半导体ETF 5分钟线，2021-11→2026-11）
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pc = (x, d = 1) => x == null || !isFinite(x) ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(d) + "%";
const KEY = "jsq.techhold";
const DEF = ["sz002463", "sh601138", "sh512760"];
// 每只的回测小结（5分钟线；ETF 数据从 2026 年才有，样本少）
const PER = {
  sz002463: { n: "沪电股份", hi: 82, up945: "−0.09%", weak: true, note: "沪电高开后'9:45还在开盘上方就拿着'这条不灵（52天，之后平均 −0.09%），高开≥2% 直接在9:45前后卖一部分更稳。低开做T 每次 +0.15%。" },
  sh601138: { n: "工业富联", hi: 86, up945: "+0.41%", note: "工业富联最符合规律：9:45还在开盘上方的，之后到收盘平均 +0.41%；在下方的 −0.06%。低开开盘买、收盘卖做T 每次 +0.80%。" },
  sh512760: { n: "半导体ETF(国泰)", hi: 13, up945: "+0.60%", note: "ETF 5分钟线只有约200天，样本太少，按同类科技股的规律做。ETF 没有印花税，做T成本低。" },
};
const loadQ = (url) => new Promise((res, rej) => { const s = document.createElement("script"); s.src = url; s.charset = "gbk"; s.async = true;
  const t = setTimeout(() => { s.remove(); rej(new Error("timeout")); }, 8000);
  s.onload = () => { clearTimeout(t); s.remove(); res(); }; s.onerror = () => { clearTimeout(t); s.remove(); rej(new Error("load")); };
  document.head.appendChild(s); });
const take = (k) => { const v = window[k]; try { delete window[k]; } catch (e) { window[k] = undefined; } return v; };
function codes() { try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); if (Array.isArray(v) && v.length) return v; } catch (e) {} return DEF; }

async function quote(sym) {
  await loadQ("https://qt.gtimg.cn/q=" + sym);
  const v = take("v_" + sym); if (typeof v !== "string") return null;
  const f = v.split("~");
  return { name: f[1], price: +f[3], prev: +f[4], open: +f[5], hi: +f[33], lo: +f[34], stamp: f[30] || "" };
}
async function minutes(sym) {     // 腾讯分时：每分钟 "HHMM 价格 累计量 累计额"
  const k = "jsq_min_" + sym;
  try {
    await loadQ(`https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=${k}&code=${sym}`);
    const j = take(k); const d = j && j.data && j.data[sym] && j.data[sym].data;
    const arr = d && (d.data || []);
    return arr.map((s) => { const p = String(s).split(" "); return { hm: p[0], px: +p[1], vol: +p[2], amt: +p[3] }; }).filter((x) => x.px > 0);
  } catch (e) { return null; }
}

function advise(q, mins, P) {
  const g = q.open / q.prev - 1, now = q.price / q.open - 1;
  const hm = q.stamp.length >= 12 ? +q.stamp.slice(8, 12) : 0;
  const m945 = mins ? mins.filter((x) => +x.hm <= 945).slice(-1)[0] : null;
  const p945 = m945 && +m945.hm >= 944 ? m945.px : null;
  const or = mins ? mins.filter((x) => +x.hm <= 945) : [];
  const orl = or.length ? Math.min(...or.map((x) => x.px)) : null;
  let cls = "", head = "", body = "";
  if (!(q.open > 0)) return { cls: "", head: "还没开盘", body: "开盘后按下面的规则看。" };
  if (g >= 0.02 && g < 0.095) {
    cls = "warn"; head = `高开 ${pc(g)}`;
    if (hm && hm < 945) body = `先别急着卖：等到 9:45 看一眼。那时还在开盘价 <b>${q.open.toFixed(2)}</b> 上方就拿着，跌到下方就卖（或减一部分）。`;
    else if (p945 != null && p945 > q.open) body = P && P.weak
      ? `9:45 是 ${p945.toFixed(2)}，在开盘价上方。同类股票这种情况之后平均还涨 +0.56%，但${P.n}自己这条不灵（之后平均 ${P.up945}）→ <b>可以先减一部分，剩下的跌破开盘15分钟最低价${orl ? " " + orl.toFixed(2) : ""}再卖</b>。`
      : `9:45 是 ${p945.toFixed(2)}，在开盘价上方 → <b>拿着</b>。同类股票这种情况之后到收盘平均 +0.56%，59% 的当天最高点在10点以后。${orl ? `要防守的话，跌破开盘15分钟最低价 ${orl.toFixed(2)} 再卖。` : ""}`;
    else if (p945 != null) body = `9:45 是 ${p945.toFixed(2)}，已经在开盘价下方 → <b>按规则该卖（或减）</b>。同类股票这种情况之后到收盘平均 −0.07%，最高点多半已经过去。`;
    else body = `9:45 时在开盘价 ${q.open.toFixed(2)} 上方就拿着，下方就卖。现在比开盘 ${pc(now)}。`;
  } else if (g <= -0.02 && g > -0.095) {
    cls = "up"; head = `低开 ${pc(g)}`;
    body = `手里有底仓、想做T的：<b>在开盘附近买</b>，收盘前卖掉同样数量。同类低开2%以上这样做平均每次 +0.26%（扣费后），一半多一点赢；别等"站上开盘15分钟高点"再买，那样平均贵2.3%。手里的别在开盘砍。现在比开盘 ${pc(now)}。`;
  } else {
    head = `开盘 ${pc(g)}`; body = `没有大跳空，按平常拿着。平开的日子做T扣费后平均是亏的，不用做。`;
  }
  return { cls, head, body };
}

async function render() {
  const box = $("techBody"); if (!box) return;
  const list = codes();
  const rows = await Promise.all(list.map(async (sym) => {
    let q = null, mins = null;
    try { q = await quote(sym); } catch (e) {}
    if (q && q.open > 0) mins = await minutes(sym);
    return { sym, q, mins };
  }));
  box.innerHTML = rows.map(({ sym, q, mins }) => {
    const P = PER[sym] || {};
    if (!q) return `<div class="tk-r"><b>${esc(P.n || sym)}</b><p class="note">行情取不到（${sym}）。</p></div>`;
    const a = advise(q, mins, P);
    const day = q.stamp.length >= 8 ? `${+q.stamp.slice(4, 6)}月${+q.stamp.slice(6, 8)}日 ${q.stamp.slice(8, 10)}:${q.stamp.slice(10, 12)}` : "";
    return `<div class="tk-r"><div class="tk-h"><b>${esc(P.n || q.name)}</b><span class="tk-p num">${q.price.toFixed(q.price < 10 ? 3 : 2)}</span><span class="chip ${a.cls}">${a.head}</span></div>
      <p>${a.body}</p>${P.note ? `<p class="note">${P.note}</p>` : ""}<p class="note">${day}；开盘 ${q.open > 0 ? q.open.toFixed(2) : "—"}，前收 ${q.prev.toFixed(2)}${mins && mins.length ? `，分时 ${mins.length} 分钟` : ""}</p></div>`;
  }).join("");
}

function init() {
  if (!$("techPanel")) return;
  $("techCodes").value = codes().join(",");
  $("techSave").addEventListener("click", () => {
    const v = $("techCodes").value.split(/[,，\s]+/).map((x) => x.trim().toLowerCase()).filter((x) => /^(sh|sz)\d{6}$/.test(x));
    if (v.length) { localStorage.setItem(KEY, JSON.stringify(v)); render(); }
  });
  const go = () => { if (!document.getElementById("tab-stock").hidden) render(); };
  document.addEventListener("jsq-tab", go);
  render();
  setInterval(go, 60e3);
}
init();
})();
