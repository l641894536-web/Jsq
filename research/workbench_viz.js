(() => {
"use strict";
// 交易台的数据图：规则小球板、价格山脊图、时钟、底部状态条（2026-11-11）
const $ = (id) => document.getElementById(id);
const RM = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
const CSSV = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const UNI = () => window.JSQ_UNIVERSE || { names: {}, groupOfSym: () => "" };
const nm = (s) => (UNI().names || {})[s] || s.replace(/USDT$/, "");
const sgn = (x, d = 1) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d);

// ---------------------------------------------------------------- 时钟
function clock() {
  const el = $("clk"); if (!el) return;
  const t = new Date(Date.now() + 8 * 3600e3), p = (x) => String(x).padStart(2, "0");
  el.textContent = `北京 ${p(t.getUTCHours())}:${p(t.getUTCMinutes())}:${p(t.getUTCSeconds())}`;
}

// ---------------------------------------------------------------- 小球板
const EDG = [-25, -15, -10, -5, 0.5, 5, 15, 30, 60, 120];      // 每笔赚亏U的分界
const NB = EDG.length + 1, ROWS = NB - 1, ZERO = EDG.indexOf(0.5) + 1;  // ZERO 起是赚钱的格子
const bucketOf = (u) => { let b = 0; while (b < EDG.length && u >= EDG[b]) b++; return b; };

function Board(root) {
  const cv = root.querySelector("canvas"), ctx = cv.getContext("2d");
  const S = { list: [], i: 0, balls: [], cnt: new Array(NB).fill(0), fin: new Array(NB).fill(0), sum: 0, win: 0, next: 0, vis: false, hold: 0, flash: new Array(NB).fill(0), W: 0, H: 290, raf: 0, last: 0 };
  const stat = (k) => root.querySelector(`[data-k="${k}"]`);
  function layout() {
    const dpr = Math.min(2.5, window.devicePixelRatio || 1); S.W = cv.clientWidth || 340;
    cv.width = Math.round(S.W * dpr); cv.height = Math.round(S.H * dpr); cv.style.height = S.H + "px"; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    S.dx = (S.W - 20) / NB; S.cx = S.W / 2; S.y0 = 22; S.dy = 11.5; S.base = S.H - 24; S.top = S.y0 + ROWS * S.dy + 22;
  }
  const bx = (b) => S.cx + (b - ROWS / 2) * S.dx;
  function set(list) {
    S.list = list; S.i = 0; S.balls = []; S.cnt.fill(0); S.fin.fill(0); S.sum = 0; S.win = 0; S.hold = 0; S.flash.fill(0);
    list.forEach((u) => S.fin[bucketOf(u)]++);
    S.max = Math.max(1, ...S.fin); S.next = performance.now() + 300;
    if (RM || !list.length) finish();
    draw(); stats();
  }
  function finish() { S.balls = []; S.i = S.list.length; S.cnt = S.fin.slice(); S.sum = S.list.reduce((a, b) => a + b, 0); S.win = S.list.filter((u) => u > 0).length; }
  function spawn(now) {
    const u = S.list[S.i], b = bucketOf(u), mv = Array(ROWS).fill(0).map((_, k) => (k < b ? 1 : 0));
    for (let k = mv.length - 1; k > 0; k--) { const j = (Math.random() * (k + 1)) | 0; [mv[k], mv[j]] = [mv[j], mv[k]]; }
    const cum = [0]; mv.forEach((m) => cum.push(cum[cum.length - 1] + m));
    S.balls.push({ u, b, cum, t0: now, sp: S.list.length > 1500 ? 34 : 52 }); S.i++;
  }
  function stats() {
    const n = S.i - S.balls.length, N = S.list.length;
    const set1 = (k, v, c) => { const e = stat(k); if (e) { e.textContent = v; e.className = c || ""; } };
    set1("n", `${n}`); const e = stat("N"); if (e) e.textContent = `/ ${N} 笔`;
    set1("w", n ? `${Math.round(S.win / n * 100)}%` : "—");
    set1("a", n ? sgn(S.sum / n) : "—", n && S.sum >= 0 ? "g" : n ? "r" : "");
    set1("s", n ? sgn(S.sum, 0) : "—", n && S.sum >= 0 ? "g" : n ? "r" : "");
  }
  function draw(now = performance.now()) {
    const W = S.W, H = S.H, ink = CSSV("--ink") || "#161718", good = CSSV("--good") || "#1E9A4C", mut = CSSV("--muted") || "#85898F";
    ctx.clearRect(0, 0, W, H);
    const xz = bx(ZERO) - S.dx / 2, n = S.cnt.reduce((a, b) => a + b, 0), wins = S.cnt.slice(ZERO).reduce((a, b) => a + b, 0);
    ctx.fillStyle = "rgba(30,154,76,.07)"; ctx.fillRect(xz, 0, W - xz, S.base);
    ctx.strokeStyle = "rgba(0,0,0,.18)"; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(xz, 4); ctx.lineTo(xz, S.base); ctx.stroke(); ctx.setLineDash([]);
    ctx.font = "500 10.5px JetBrains Mono, monospace"; ctx.textBaseline = "top";
    ctx.fillStyle = mut; ctx.textAlign = "left"; ctx.fillText(`亏 ${n ? Math.round((n - wins) / n * 100) : 0}%`, 6, 6);
    ctx.fillStyle = good; ctx.textAlign = "right"; ctx.fillText(`赚 ${n ? Math.round(wins / n * 100) : 0}%`, W - 6, 6);
    // 漏斗口
    ctx.fillStyle = ink; ctx.beginPath(); ctx.moveTo(S.cx - 6, 4); ctx.lineTo(S.cx + 6, 4); ctx.lineTo(S.cx, 13); ctx.closePath(); ctx.fill();
    // 钉子
    ctx.fillStyle = "#C3C6CA";
    for (let r = 0; r < ROWS; r++) for (let k = 0; k <= r; k++) { ctx.beginPath(); ctx.arc(S.cx + (k - r / 2) * S.dx, S.y0 + r * S.dy + 6, 1.5, 0, 6.3); ctx.fill(); }
    // 柱子
    const mh = S.base - S.top;
    for (let b = 0; b < NB; b++) {
      const h = S.cnt[b] / S.max * mh, x = bx(b) - S.dx * 0.42, w = S.dx * 0.84, fl = Math.max(0, 1 - (now - S.flash[b]) / 260);
      ctx.fillStyle = b >= ZERO ? good : b <= 1 ? "#6E7277" : "#A3A7AC";
      ctx.fillRect(x, S.base - h, w, h);
      if (fl > 0 && h > 0) { ctx.fillStyle = `rgba(255,255,255,${0.55 * fl})`; ctx.fillRect(x, S.base - h, w, Math.min(h, 6)); }
      if (S.cnt[b] && h > 13) { ctx.fillStyle = b >= ZERO ? "#fff" : "#fff"; ctx.font = "500 9.5px JetBrains Mono, monospace"; ctx.textAlign = "center"; ctx.fillText(S.cnt[b], bx(b), S.base - h + 2); }
    }
    ctx.strokeStyle = ink; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(4, S.base + 0.5); ctx.lineTo(W - 4, S.base + 0.5); ctx.stroke();
    ctx.fillStyle = mut; ctx.font = "500 9.5px JetBrains Mono, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "top";
    EDG.forEach((v, k) => { const x = bx(k) + S.dx / 2; ctx.fillText(v === 0.5 ? "0" : v > 0 ? "+" + v : "−" + -v, x, S.base + 6); });
    // 小球
    for (const o of S.balls) {
      const p = (now - o.t0) / o.sp; let x, y;
      if (p < ROWS) { const s = Math.floor(p), f = p - s, x0 = S.cx + (o.cum[s] - s / 2) * S.dx, x1 = S.cx + (o.cum[s + 1] - (s + 1) / 2) * S.dx;
        x = x0 + (x1 - x0) * f; y = S.y0 + s * S.dy + f * S.dy - Math.sin(Math.PI * f) * S.dy * 0.55; }
      else { const f = Math.min(1, (p - ROWS) / 3), tgt = S.base - S.cnt[o.b] / S.max * mh - 4; x = bx(o.b); y = S.y0 + ROWS * S.dy + f * f * (tgt - S.y0 - ROWS * S.dy); }
      ctx.fillStyle = o.u > 0 ? good : ink; ctx.beginPath(); ctx.arc(x, y, 3.1, 0, 6.3); ctx.fill();
    }
  }
  function frame(now) {
    S.raf = 0; if (!S.vis || document.hidden) return;
    if (S.i >= S.list.length && !S.balls.length) {
      if (!S.hold) S.hold = now + 6000;
      else if (now > S.hold && !RM) { set(S.list); }
    } else {
      let k = 0;
      while (S.i < S.list.length && now >= S.next && k < 12) { spawn(now); const iv = Math.max(Math.max(5, 26000 / S.list.length), 200 * Math.pow(0.982, S.i)); S.next += iv; k++; }
      if (now - S.next > 1000) S.next = now;
      S.balls = S.balls.filter((o) => { if ((now - o.t0) / o.sp >= ROWS + 3) { S.cnt[o.b]++; S.sum += o.u; if (o.u > 0) S.win++; S.flash[o.b] = now; return false; } return true; });
      if (now - S.last > 120) { stats(); S.last = now; }
    }
    draw(now); go();
  }
  function go() { if (!S.raf && S.vis && !document.hidden && !RM) S.raf = requestAnimationFrame(frame); }
  layout();
  if ("IntersectionObserver" in window) new IntersectionObserver((es) => { S.vis = es[0].isIntersecting; if (S.vis) { S.next = Math.max(S.next, performance.now()); go(); } }, { threshold: 0.05 }).observe(cv);
  else S.vis = true;
  if ("ResizeObserver" in window) new ResizeObserver(() => { const w = cv.clientWidth; if (w && Math.abs(w - S.W) > 2) { layout(); draw(); } }).observe(cv);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { S.next = performance.now(); go(); } });
  return { set, get n() { return S.list.length; } };
}

let BALLS = null;
async function loadBalls() {
  if (BALLS) return BALLS;
  try { const r = await fetch("balls.json", { cache: "no-store" }); if (r.ok) BALLS = await r.json(); } catch (e) {}
  return BALLS;
}
const pick = (d, f) => d.t.filter(f).map((x) => x[2]);

async function initBoards() {
  const d = await loadBalls(); if (!d) return;
  const all = pick(d, () => true);
  const span = `${d.from.slice(0, 7)} ~ ${d.to.slice(0, 7)}`;
  const ra = $("ballAll");
  if (ra) { const b = Board(ra); b.set(all); const m = ra.querySelector(".meta"); if (m) m.textContent = `${span} · ${all.length} 笔`; }
  const rc = $("ballPanel"); if (!rc) return;
  const bc = Board(rc); let mode = "sym", cur = "";
  const seg = rc.querySelector(".seg"), meta = rc.querySelector(".meta"), cap = rc.querySelector(".viz-cap");
  function apply() {
    const sym = (window.JSQ && window.JSQ.state && window.JSQ.state.sym) || "", si = d.syms.indexOf(sym), mine = si >= 0 ? pick(d, (x) => x[0] === si) : [];
    const useSym = mode === "sym" && mine.length >= 20;
    seg.querySelector('[data-m="sym"]').textContent = si >= 0 ? `${nm(sym)} ${mine.length}笔` : `${nm(sym)}（没有）`;
    seg.querySelector('[data-m="sym"]').disabled = mine.length < 20;
    seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.m === (useSym ? "sym" : "all"))));
    const L = useSym ? mine : all, key = (useSym ? sym : "all") + L.length; if (key === cur) return; cur = key;
    bc.set(L);
    meta.textContent = `${span}`;
    const wins = L.filter((u) => u > 0).length, avg = L.reduce((a, b) => a + b, 0) / Math.max(1, L.length);
    cap.innerHTML = `${useSym ? `<b>${nm(sym)}</b>按交易台现行规则` : "交易台现行规则在12个品种上"}近5年做过的每一笔是一颗球（按100U开5倍算），落进"这一笔赚亏多少U"的格子。` +
      `赚钱的只有 <b>${Math.round(wins / L.length * 100)}%</b>，多数是小亏；平均每笔 <b>${sgn(avg)}U</b> 靠的是右边少数大赚。<b>单笔像抛硬币，优势只在次数多了以后才显出来</b>，所以止损要守、仓位要小、不能挑着做。` +
      (si < 0 ? ` ${nm(sym)}不在验证过的品种里，这里显示的是全部规则。` : "");
  }
  seg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b || b.disabled) return; mode = b.dataset.m; apply(); });
  apply(); setInterval(apply, 1500);
}

// ---------------------------------------------------------------- 山脊图：接下来几天价格可能落在哪
const HZ = [1 / 24, 2 / 24, 4 / 24, 8 / 24, 0.5, 1, 2, 3, 4, 5];
const HZL = ["1小时", "2小时", "4小时", "8小时", "12小时", "1天", "2天", "3天", "4天", "5天"];
const Phi = (z) => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2), p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - p : p; };
const SIG = {};
async function sigmaOf(sym) {
  if (SIG[sym] && Date.now() - SIG[sym].at < 30 * 60e3) return SIG[sym].s;
  const r = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${sym}&interval=1d&limit=40`, { cache: "no-store" }); if (!r.ok) return null;
  let k = await r.json(); if (!Array.isArray(k) || k.length < 15) return null;
  k = k.slice(0, -1);
  if (UNI().groupOfSym && UNI().groupOfSym(sym) === "stock") k = k.filter((x) => { const w = new Date(+x[0]).getUTCDay(); return w !== 0 && w !== 6; });
  const c = k.slice(-21).map((x) => +x[4]), lr = c.slice(1).map((x, i) => Math.log(x / c[i]));
  const m = lr.reduce((a, b) => a + b, 0) / lr.length, s = Math.sqrt(lr.reduce((a, b) => a + (b - m) ** 2, 0) / (lr.length - 1));
  SIG[sym] = { s, at: Date.now() }; return s;
}
function levelsOf(sym) {
  const P = window.JSQ_PLAN ? window.JSQ_PLAN() : null;
  if (P && P.stop && P.E0) return { stop: P.stop, target: P.target, side: P.side || 1, from: "plan" };
  try { const o = JSON.parse(localStorage.getItem("jsq.pos." + sym) || "{}"); const S2 = parseFloat(o.S), E = parseFloat(o.E);
    if (S2 > 0 && E > 0) return { stop: S2, target: null, side: +o.side || 1, from: "pos" }; } catch (e) {}
  return null;
}
const lastPx = () => { const t = ($("px") || {}).textContent || ""; const v = parseFloat(t.replace(/[^\d.]/g, "")); return isFinite(v) && v > 0 ? v : null; };
const fmtP = (x) => x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 1 }) : x >= 10 ? x.toFixed(2) : x >= 1 ? x.toFixed(3) : x.toFixed(5);

function drawRidge(cv, o, t = 1) {
  const dpr = Math.min(2.5, window.devicePixelRatio || 1), W = cv.clientWidth || 340, H = 250, ctx = cv.getContext("2d");
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px"; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const ink = CSSV("--ink") || "#161718", mut = CSSV("--muted") || "#85898F", bad = CSSV("--bad") || "#D3203B", good = CSSV("--good") || "#1E9A4C";
  const s5 = o.sd * Math.sqrt(5); let lo = -2.4 * s5, hi = 2.4 * s5;
  const lv = (p) => Math.log(p / o.last);
  for (const p of [o.stop, o.target]) if (p) { const v = lv(p); if (Math.abs(v) < 5 * s5) { lo = Math.min(lo, v - 0.4 * s5); hi = Math.max(hi, v + 0.4 * s5); } }
  const L = 46, R = 14, N = HZ.length, gap = 12.5, yF = H - 26, hp = 64;
  const X0 = (v) => L + (v - lo) / (hi - lo) * (W - L - R - 24);
  const X = (v, k) => X0(v) + (N - 1 - k) * 2.6;          // 越远的越往右、越往上（透视）
  const Y = (k) => yF - (N - 1 - k) * gap;                  // k=N-1 最前（5天），k=0 最后（1小时）
  const vS = o.stop ? lv(o.stop) : null, vT = o.target ? lv(o.target) : null, side = o.side || 1;
  const shown = Math.ceil(t * N);
  for (let k = 0; k < N; k++) {
    if (N - 1 - k >= shown) continue;
    const sg = o.sd * Math.sqrt(HZ[k]), y0 = Y(k), pts = [];
    for (let i = 0; i <= 120; i++) { const v = lo + (hi - lo) * i / 120; pts.push([X(v, k), y0 - hp * Math.exp(-0.5 * (v / sg) ** 2), v]); }
    const path = () => { ctx.beginPath(); ctx.moveTo(pts[0][0], y0); pts.forEach((p) => ctx.lineTo(p[0], p[1])); ctx.lineTo(pts[pts.length - 1][0], y0); ctx.closePath(); };
    path(); ctx.fillStyle = "#fff"; ctx.fill();
    const tail = (a, b, col) => { ctx.save(); path(); ctx.clip(); ctx.fillStyle = col; ctx.fillRect(Math.min(a, b), 0, Math.abs(b - a), H); ctx.restore(); };
    if (vS != null) tail(side === 1 ? 0 : X(vS, k), side === 1 ? X(vS, k) : W, "rgba(211,32,59,.62)");
    if (vT != null) tail(side === 1 ? X(vT, k) : 0, side === 1 ? W : X(vT, k), "rgba(30,154,76,.45)");
    path(); ctx.strokeStyle = ink; ctx.lineWidth = k === N - 1 || k === 5 ? 1.3 : 0.8; ctx.stroke();
    if (k === 0 || k === 5 || k === N - 1) { ctx.fillStyle = mut; ctx.font = "500 10px JetBrains Mono, monospace"; ctx.textAlign = "right"; ctx.textBaseline = "middle"; ctx.fillText(HZL[k], L - 6, y0 - 2); }
  }
  const vline = (v, col, dash, label, up) => {
    if (v == null || v < lo || v > hi) return; ctx.strokeStyle = col; ctx.setLineDash(dash); ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(X(v, N - 1), yF + 4); ctx.lineTo(X(v, 0), Y(0) - hp - 6); ctx.stroke(); ctx.setLineDash([]);
    if (label) { ctx.font = "600 10.5px JetBrains Mono, monospace"; const tw = ctx.measureText(label).width + 10, x = Math.min(W - tw - 2, Math.max(2, X(v, 0) - tw / 2)), y = up ? 2 : 16;
      ctx.fillStyle = col; ctx.fillRect(x, y, tw, 15); ctx.fillStyle = "#fff"; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(label, x + 5, y + 8); }
  };
  vline(0, ink, [2, 3], `现价 ${fmtP(o.last)}`, true);
  if (vS != null) vline(vS, bad, [5, 3], `止损 ${fmtP(o.stop)}`, false);
  if (vT != null) vline(vT, good, [5, 3], `目标 ${fmtP(o.target)}`, false);
  ctx.fillStyle = mut; ctx.font = "500 10px JetBrains Mono, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const f of [-2, -1, 1, 2]) { const v = f * s5; if (v > lo && v < hi) ctx.fillText(fmtP(o.last * Math.exp(v)), X(v, N - 1), yF + 7); }
}

let RG = { sym: "", key: "", anim: 0 };
async function updRidge(force) {
  const box = $("ridgePanel"); if (!box || !window.JSQ || !window.JSQ.state) return;
  const sym = window.JSQ.state.sym, last = lastPx(); if (!sym || !last) return;
  let sd = null; try { sd = await sigmaOf(sym); } catch (e) {}
  if (!sd) { box.hidden = true; return; } box.hidden = false;
  const lv = levelsOf(sym), o = Object.assign({ last, sd }, lv || {});
  const key = [sym, lv && lv.stop, lv && lv.target, Math.round(Math.log(last) / (sd * 0.25))].join("|");
  const cv = $("ridgeCv"), big = $("ridgeBig"), cap = $("ridgeCap"), leg = $("ridgeKey");
  const d1 = sd, lo80 = last * Math.exp(-1.2816 * d1), hi80 = last * Math.exp(1.2816 * d1);
  $("ridgeMeta").textContent = `${nm(sym)} · 最近20天每天波动 ±${(sd * 100).toFixed(1)}%`;
  if (lv) {
    const dS = Math.abs(Math.log(lv.stop / last)), pS = Math.min(1, 2 * Phi(-dS / (sd * Math.sqrt(5)))), p1 = Math.min(1, 2 * Phi(-dS / sd));
    const pT = lv.target ? Math.min(1, 2 * Phi(-Math.abs(Math.log(lv.target / last)) / (sd * Math.sqrt(5)))) : null;
    big.innerHTML = `<b>${Math.round(pS * 100)}%</b><span>5天内价格碰到止损 ${fmtP(lv.stop)} 的可能（1天内 ${Math.round(p1 * 100)}%）</span>`;
    leg.innerHTML = `<span class="n"><i></i>现价</span><span class="s"><i></i>${lv.from === "plan" ? "规则止损" : "你填的止损"}</span>` + (lv.target ? `<span class="t"><i></i>目标（5天内碰到约 ${Math.round(pT * 100)}%）</span>` : "");
    cap.innerHTML = `每一层是一个时间点上价格可能的分布：最后面一层是1小时后，最前面一层是5天后，越往后越摊开。<b>红色那块</b>就是落到止损外面的部分。` +
      `这是把最近20天的波动当成"随机晃动"算出来的，没算趋势和消息，只用来判断<b>止损是不是放得太近、会不会被正常波动扫掉</b>。`;
  } else {
    big.innerHTML = `<b style="color:var(--ink)">${fmtP(lo80)} ~ ${fmtP(hi80)}</b><span>明天这个时候，8成落在这个范围里</span>`;
    leg.innerHTML = `<span class="n"><i></i>现价</span>`;
    cap.innerHTML = `每一层是一个时间点上价格可能的分布：最后面一层是1小时后，最前面一层是5天后，越往后越摊开。按最近20天的波动粗算，没算趋势和消息。` +
      `这个品种现在没有进场计划；在"我已经有仓位"里填上止损，这里会算出被正常波动扫到止损的可能。`;
  }
  if (!force && key === RG.key) return;
  const fresh = sym !== RG.sym; RG.key = key; RG.sym = sym;
  cancelAnimationFrame(RG.anim);
  if (fresh && !RM) { const t0 = performance.now(); const step = (now) => { const t = Math.min(1, (now - t0) / 900); drawRidge(cv, o, t); if (t < 1) RG.anim = requestAnimationFrame(step); }; RG.anim = requestAnimationFrame(step); }
  else drawRidge(cv, o, 1);
}


// ---------------------------------------------------------------- 验证页：规则体检、模拟账户、每半年成绩、实际 vs 预期、影子规则、进化日志
const GRPN = (sym) => { const g = UNI().groupOfSym(sym); return g === "metal" ? "金银" : g === "crypto" ? "币" : "股票"; };
const st = (a) => { const n = a.length, m = n ? a.reduce((x, y) => x + y, 0) / n : 0, sd = n > 1 ? Math.sqrt(a.reduce((x, y) => x + (y - m) * (y - m), 0) / (n - 1)) : 0; return { n, m, sd, sum: m * n, win: n ? a.filter((u) => u > 0).length / n : 0 }; };
const qtl = (a, q) => { const b = a.slice().sort((x, y) => x - y), i = (b.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i); return b[lo] + (b[hi] - b[lo]) * (i - lo); };
let LEDGER = null, EVO = null;
async function loadJSON(u) { try { const r = await fetch(u, { cache: "no-store" }); if (r.ok) return await r.json(); } catch (e) {} return null; }
const acct0 = () => { let a = NaN; try { a = parseFloat(localStorage.getItem("jsq.acct")); } catch (e) {} return a > 0 ? a : 3200; };
function canvasCtx(cv, H) {
  const dpr = Math.min(2.5, window.devicePixelRatio || 1), W = cv.clientWidth || 340;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px";
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); return { ctx, W, H };
}

// 模拟仓（页面实时推过的）转成和 ledger.json 一样的格式
function paperAsLedger(L) {
  const P = window.JSQ_PAPER; if (!P) return L;
  const tr = P.book.map((b) => ({ t_in: new Date(b.t_in).toISOString(), u: +b.u || 0, status: b.status }));
  return Object.assign({}, L || {}, { trades: tr, n: tr.length, closed: P.cl.length, open: P.op.length, total_u: Math.round((P.closedU + P.openU) * 10) / 10, frozen: P.frozen || (L && L.frozen) });
}
function renderValHead(B, L0) {
  const el = $("valBig"); if (!el || !B) return; const L = paperAsLedger(L0);
  const all = B.t.map((x) => x[2]), S = st(all);
  const n = L ? L.n || 0 : 0, tot = L ? L.total_u || 0 : 0;
  // 自动体检：每条规则最近一个半年是不是明显变差（笔数够、平均亏）
  const half = (ym) => Math.floor(ym / 100) * 2 + (ym % 100 > 6 ? 1 : 0), H = {}, hmax = Math.max(...B.t.map((x) => half(x[3])));
  for (const [si, ri, u, ym] of B.t) { const k = `${GRPN(B.syms[si])}·${B.rules[ri]}`, h = half(ym); ((H[k] = H[k] || {})[h] = H[k][h] || []).push(u); }
  const W = [];
  for (const k of Object.keys(H)) { const a = H[k][hmax] || []; if (a.length < 15) continue; const s1 = st(a); if (s1.m >= 0) continue;
    let g = 0, t = 0; for (const h of Object.keys(H[k])) { const s2 = st(H[k][h]); t++; if (s2.m > 0) g++; } W.push({ k, n: a.length, m: s1.m, g, t }); }
  const lo = S.m * n - 1.64 * S.sd * Math.sqrt(n), hi = S.m * n + 1.64 * S.sd * Math.sqrt(n);
  let v;
  if (!L) v = "自动记账还没载入。";
  else if (n < 10) v = `规则定下以后才 <b>${n}</b> 笔，太少，看不出好坏：按回测，至少要30笔左右，才分得清是规则的问题还是运气。现在照做、不挑单。`;
  else if (tot < lo) v = `<b class="r">低于正常范围</b>：${n} 笔按回测应该在 ${sgn(lo, 0)} ~ ${sgn(hi, 0)}U 之间，实际 ${sgn(tot, 0)}U。要停下来查是不是行情变了。`;
  else if (tot > hi) v = `<b class="g">好于正常范围</b>：${n} 笔按回测应该在 ${sgn(lo, 0)} ~ ${sgn(hi, 0)}U 之间，实际 ${sgn(tot, 0)}U。多半是运气好，别因此加大仓位。`;
  else v = `<b>在正常范围里</b>：${n} 笔按回测应该在 ${sgn(lo, 0)} ~ ${sgn(hi, 0)}U 之间，实际 ${sgn(tot, 0)}U。照做。`;
  el.innerHTML = `<div><small>近5年回测 · 平均每笔</small><b class="${S.m >= 0 ? "g" : "r"}">${sgn(S.m)}U</b><p>${S.n} 笔，赚钱的 ${Math.round(S.win * 100)}%，合计 ${sgn(S.sum, 0)}U</p></div>` +
    `<div><small>规则定下以后 · 合计</small><b class="${tot >= 0 ? "g" : "r"}">${sgn(tot)}U</b><p>${n} 笔${L ? `（已平 ${L.closed || 0}，持仓中 ${L.open || 0}）` : ""}，${L && L.frozen ? L.frozen.slice(5).replace("-", "月") + "日起" : ""}</p></div>` +
    `<div class="verdict"><span>${v}</span></div>` + (W.length ? `<div class="verdict warnrow"><span><b class="r">最近半年变差的：</b>${W.map((w) => `${w.k}（${w.n}笔，平均${sgn(w.m, 0)}U；5年里 ${w.g}/${w.t} 个半年是赚的）`).join("、")}。一个半年亏不等于规则失效，但要盯着：规则定下以后这几条的自动记账攒到15笔还是亏的，就先停掉、重新验证。</span></div>` : "");
  const sub = $("valSub"); if (sub) sub.textContent = L && L.data_to ? `记账数据到 ${String(L.data_to).slice(5, 10).replace("-", "月")}日` : "";
}

// 模拟账户：把过去5年每个月的真实合计打乱重排，模拟几百种未来
const MC = { m: 12, paths: null, key: "", anim: 0 };
function mcSim(B, M) {
  const by = {}; for (const x of B.t) by[x[3]] = (by[x[3]] || 0) + x[2];
  const months = []; let y = +B.from.slice(2, 4), m = +B.from.slice(5, 7); const end = +B.to.slice(2, 4) * 100 + +B.to.slice(5, 7);
  while (y * 100 + m <= end) { months.push(by[y * 100 + m] || 0); m++; if (m > 12) { m = 1; y++; } }
  const A0 = acct0(), N = 500, P = [], dd = [], fin = [];
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let k = 0; k < N; k++) { const p = [A0]; let peak = A0, mdd = 0; for (let i = 0; i < M; i++) { const v = p[i] + months[Math.floor(rnd() * months.length)]; p.push(v); peak = Math.max(peak, v); mdd = Math.max(mdd, peak - v); } P.push(p); dd.push(mdd); fin.push(p[M] - A0); }
  const band = []; for (let i = 0; i <= M; i++) { const col = P.map((p) => p[i]); band.push([0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95].map((q) => qtl(col, q))); }
  return { A0, P, band, dd, fin, months };
}
function drawMC(cv, R, M, t) {
  const { ctx, W, H } = canvasCtx(cv, 260), padL = 8, padR = 74, padT = 14, padB = 22;
  let lo = Infinity, hi = -Infinity; for (const b of R.band) { lo = Math.min(lo, b[0]); hi = Math.max(hi, b[6]); }
  lo = Math.min(lo, R.A0); hi = Math.max(hi, R.A0); const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = (i) => padL + (W - padL - padR) * i / M, Y = (v) => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo));
  const ink = CSSV("--ink") || "#161718", mut = CSSV("--muted") || "#85898F", good = CSSV("--good") || "#1E9A4C", bad = CSSV("--bad") || "#D3203B", hair = CSSV("--hair") || "#E8E9EA";
  ctx.clearRect(0, 0, W, H);
  // 起点线：今天的账户
  ctx.strokeStyle = mut; ctx.setLineDash([4, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, Y(R.A0)); ctx.lineTo(W - padR, Y(R.A0)); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = mut; ctx.font = "500 10px " + (CSSV("--font-num") || "monospace"); ctx.textAlign = "left"; ctx.fillText(`今天 ${Math.round(R.A0)}U`, padL + 2, Y(R.A0) - 4);
  // 月份刻度
  ctx.fillStyle = mut; ctx.textAlign = "center";
  for (let i = 0; i <= M; i += M > 6 ? 3 : 1) { ctx.fillText(i === 0 ? "现在" : `${i}个月`, X(i), H - 6); ctx.strokeStyle = hair; ctx.beginPath(); ctx.moveTo(X(i), padT); ctx.lineTo(X(i), H - padB); ctx.stroke(); }
  const upto = Math.max(0.0001, t) * M;
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, X(upto) + 1, H); ctx.clip();
  // 一部分单独的路径（细线），再叠上 10%-90% 和 25%-75% 的带子
  ctx.lineWidth = 1;
  for (let k = 0; k < 70; k++) { const p = R.P[k]; ctx.strokeStyle = p[M] >= R.A0 ? "rgba(30,154,76,.16)" : "rgba(211,32,59,.16)"; ctx.beginPath(); p.forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))); ctx.stroke(); }
  const area = (a, b, col) => { ctx.fillStyle = col; ctx.beginPath(); R.band.forEach((q, i) => i ? ctx.lineTo(X(i), Y(q[a])) : ctx.moveTo(X(i), Y(q[a]))); for (let i = M; i >= 0; i--) ctx.lineTo(X(i), Y(R.band[i][b])); ctx.closePath(); ctx.fill(); };
  area(1, 5, "rgba(22,23,24,.07)"); area(2, 4, "rgba(22,23,24,.10)");
  const med = R.band[M][3]; ctx.strokeStyle = med >= R.A0 ? good : bad; ctx.lineWidth = 2.2; ctx.beginPath(); R.band.forEach((q, i) => i ? ctx.lineTo(X(i), Y(q[3])) : ctx.moveTo(X(i), Y(q[3]))); ctx.stroke();
  ctx.restore();
  if (t >= 1) {
    ctx.textAlign = "left"; ctx.font = "600 10.5px " + (CSSV("--font-num") || "monospace");
    const lab = [[5, "好的10%", ink], [3, "中间", med >= R.A0 ? good : bad], [1, "差的10%", ink]], ys = [];
    for (const [qi, txt, col] of lab) { let y = Y(R.band[M][qi]); for (const y0 of ys) if (Math.abs(y - y0) < 24) y = y0 + (y > y0 ? 24 : -24); ys.push(y);
      ctx.fillStyle = col; ctx.fillText(txt, W - padR + 6, y - 2); ctx.fillStyle = mut; ctx.font = "500 10px " + (CSSV("--font-num") || "monospace"); ctx.fillText(`${Math.round(R.band[M][qi])}U`, W - padR + 6, y + 10); ctx.font = "600 10.5px " + (CSSV("--font-num") || "monospace"); }
  }
}
function renderMC(B, force) {
  const cv = $("mcCv"); if (!cv || !B) return;
  const M = MC.m, key = M + "|" + acct0() + "|" + (cv.clientWidth || 0); if (!force && key === MC.key) return; MC.key = key;
  const R = mcSim(B, M), A0 = R.A0;
  const pLoss = R.fin.filter((x) => x < 0).length / R.fin.length, medDD = qtl(R.dd, 0.5), badDD = qtl(R.dd, 0.9);
  const stEl = $("mcStats");
  if (stEl) stEl.innerHTML = `<div><small>中间情况</small><b class="${R.band[M][3] >= A0 ? "g" : "r"}">${sgn(R.band[M][3] - A0, 0)}</b></div><div><small>亏钱概率</small><b class="${pLoss > 0.3 ? "r" : ""}">${Math.round(pLoss * 100)}%</b></div>` +
    `<div><small>差的10%</small><b class="${R.band[M][1] >= A0 ? "g" : "r"}">${sgn(R.band[M][1] - A0, 0)}</b></div><div><small>中途回撤</small><b>${Math.round(medDD)}U</b></div>`;
  const mt = $("mcMeta"); if (mt) mt.textContent = `从 ${Math.round(A0)}U 开始 · 500 种可能 · 按100U开5倍`;
  const cap = $("mcCap");
  if (cap) cap.innerHTML = `把过去5年每个月的真实成绩（${R.months.length} 个月）随机打乱重排，模拟 500 种未来：每条细线是一种可能，灰色带子里是中间八成的情况。` +
    `照规则做 ${M === 12 ? "一年" : M + " 个月"}，最后亏钱的可能约 <b>${Math.round(pLoss * 100)}%</b>；中途从高点回撤一般 <b>${Math.round(medDD)}U</b>，差的时候 <b>${Math.round(badDD)}U</b>——<b>这些回撤是正常的，不是规则坏了</b>。` +
    `前提：验证过的品种出信号都做、每笔100U开5倍、不挑单。只是概率，不是预测。`;
  cancelAnimationFrame(MC.anim);
  if (RM) drawMC(cv, R, M, 1);
  else { const t0 = performance.now(); const step = (now) => { const t = Math.min(1, (now - t0) / 1100); drawMC(cv, R, M, t); if (t < 1) MC.anim = requestAnimationFrame(step); }; MC.anim = requestAnimationFrame(step); }
}

// 每条规则每半年的成绩
function renderHeat(B) {
  const el = $("heatBox"); if (!el || !B) return;
  const half = (yymm) => { const y = Math.floor(yymm / 100), m = yymm % 100; return y * 2 + (m > 6 ? 1 : 0); };
  const rows = {}, cols = new Set();
  for (const [si, ri, u, ym] of B.t) { const k = `${GRPN(B.syms[si])} · ${B.rules[ri]}`, h = half(ym); cols.add(h); (rows[k] = rows[k] || {}); (rows[k][h] = rows[k][h] || []).push(u); (rows["全部"] = rows["全部"] || {}); (rows["全部"][h] = rows["全部"][h] || []).push(u); }
  const C = [...cols].sort((a, b) => a - b), order = Object.keys(rows).filter((k) => k !== "全部").sort().concat(["全部"]);
  const col = (avg) => { const a = Math.min(1, Math.abs(avg) / 12); return avg >= 0 ? `rgba(30,154,76,${0.12 + a * 0.6})` : `rgba(211,32,59,${0.12 + a * 0.6})`; };
  const hd = (k) => k === "全部" ? "全部" : k.replace(" · ", "<br>").replace("指标转多", "指标").replace("回调企稳", "企稳");
  let html = `<table><thead><tr><th></th>${order.map((k) => `<th class="c">${hd(k)}</th>`).join("")}</tr></thead><tbody>`;
  const cnt = {}; for (const k of order) cnt[k] = [0, 0];
  for (const h of C) {
    html += `<tr><th>${String(Math.floor(h / 2)).padStart(2, "0")}年${h % 2 ? "下" : "上"}</th>` + order.map((k) => { const a = (rows[k] || {})[h]; if (!a || !a.length) return `<td class="e">·</td>`; const s2 = st(a); cnt[k][1]++; if (s2.m > 0) cnt[k][0]++; return `<td style="background:${col(s2.m)}" title="${k} ${s2.n}笔 平均${sgn(s2.m)}U">${s2.m >= 0 ? "+" : "−"}${Math.abs(s2.m).toFixed(0)}<small>${s2.n}</small></td>`; }).join("") + `</tr>`;
  }
  html += `<tr class="tot"><th>赚的半年</th>${order.map((k) => `<td>${cnt[k][0]}/${cnt[k][1]}</td>`).join("")}</tr>`;
  el.innerHTML = html + "</tbody></table>";
  const sum = order.map((k) => [k, cnt[k][0], cnt[k][1]]);
  const cap = $("heatCap"), A = sum.find((x) => x[0] === "全部");
  if (cap) cap.innerHTML = `每一格是一条规则在那半年里<b>平均每笔赚亏多少U</b>（小字是笔数）；绿色是赚，红色是亏，颜色越深越多。一条规则要<b>大多数半年是绿的</b>，才说明不是碰上了某一段好行情。` +
    (A ? `全部规则合起来 ${A[2]} 个半年里有 <b>${A[1]}</b> 个是赚的。` : "") + `格子很浅或笔数很少的，那半年说明不了什么。`;
}

// 规则定下以后：实际累计 vs 回测预期范围
function drawFwd(cv, L, B) {
  const all = B.t.map((x) => x[2]), S = st(all);
  const tr = (L && L.trades ? L.trades.slice() : []).sort((a, b) => String(a.t_in).localeCompare(String(b.t_in)));
  const n = tr.length, K = Math.max(30, n + 5);
  const { ctx, W, H } = canvasCtx(cv, 190), padL = 34, padR = 10, padT = 10, padB = 20;
  const cum = [0]; for (const x of tr) cum.push(cum[cum.length - 1] + (+x.u || 0));
  let lo = Math.min(0, ...cum, S.m * K - 1.64 * S.sd * Math.sqrt(K)), hi = Math.max(0, ...cum, S.m * K + 1.64 * S.sd * Math.sqrt(K)); const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
  const X = (k) => padL + (W - padL - padR) * k / K, Y = (v) => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo));
  const ink = CSSV("--ink") || "#161718", mut = CSSV("--muted") || "#85898F", good = CSSV("--good") || "#1E9A4C", bad = CSSV("--bad") || "#D3203B", hair = CSSV("--hair") || "#E8E9EA";
  ctx.clearRect(0, 0, W, H); ctx.font = "500 10px " + (CSSV("--font-num") || "monospace");
  ctx.fillStyle = "rgba(22,23,24,.08)"; ctx.beginPath();
  for (let k = 0; k <= K; k++) { const v = S.m * k + 1.64 * S.sd * Math.sqrt(k); k ? ctx.lineTo(X(k), Y(v)) : ctx.moveTo(X(k), Y(v)); }
  for (let k = K; k >= 0; k--) ctx.lineTo(X(k), Y(S.m * k - 1.64 * S.sd * Math.sqrt(k))); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = mut; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(K), Y(S.m * K)); ctx.stroke(); ctx.setLineDash([]);
  ctx.strokeStyle = hair; ctx.beginPath(); ctx.moveTo(padL, Y(0)); ctx.lineTo(W - padR, Y(0)); ctx.stroke();
  ctx.fillStyle = mut; ctx.textAlign = "right"; ctx.fillText("0", padL - 4, Y(0) + 3); ctx.fillText(sgn(hi, 0), padL - 4, padT + 8); ctx.fillText(sgn(lo, 0), padL - 4, H - padB);
  ctx.textAlign = "center"; for (const k of [0, 10, 20, 30, 40, 60, 80, 100].filter((k) => k <= K)) ctx.fillText(k ? `${k}笔` : "", X(k), H - 5);
  ctx.textAlign = "left"; ctx.fillText("回测预期", X(K * 0.62), Y(S.m * K * 0.62) - 8);
  if (n) {
    ctx.strokeStyle = ink; ctx.lineWidth = 2; ctx.beginPath(); cum.forEach((v, k) => k ? ctx.lineTo(X(k), Y(v)) : ctx.moveTo(X(k), Y(v))); ctx.stroke();
    tr.forEach((x, i) => { ctx.beginPath(); ctx.arc(X(i + 1), Y(cum[i + 1]), 3.5, 0, 7); if (x.status === "已平") { ctx.fillStyle = x.u >= 0 ? good : bad; ctx.fill(); } else { ctx.fillStyle = "#fff"; ctx.fill(); ctx.strokeStyle = (+x.u >= 0 ? good : bad); ctx.lineWidth = 1.5; ctx.stroke(); } });
  }
  return { n, tot: cum[n], S, K };
}
function renderFwd(L0, B) {
  const cv = $("fwdCv"); if (!cv || !B) return; const L = paperAsLedger(L0);
  const r = drawFwd(cv, L, B), cap = $("fwdCap");
  if (cap) cap.innerHTML = `黑线是规则定下以后自动记账的累计盈亏（实心点是已平的单，空心点是还没平的），灰色带子是按回测算出来的<b>正常范围</b>（九成的情况落在里面）。` +
    `<b>线一直在带子里就照做；掉到带子下面才说明规则可能失效</b>，要停下来查。` + (r.n < 30 ? `现在才 ${r.n} 笔，判断不了，至少等到30笔。` : "");
}

function renderShadow(L) {
  const el = $("shadowBox"); if (!el) return;
  if (!L) { el.innerHTML = `<p class="note">载入中…</p>`; return; }
  const sh = L.shadow || [];
  if (!sh.length) { el.innerHTML = `<p class="note">影子记账从下一次数据更新开始（每天北京时间早上）。</p>`; return; }
  const row = (nm, why, n, cl, u, me) => `<tr${me ? ' class="me"' : ""}><td><b>${nm}</b><small>${why}</small></td><td class="n">${n} 笔${cl != null ? `<small>已平 ${cl}</small>` : ""}</td><td class="n"><b style="color:var(${u >= 0 ? "--good" : "--bad"})">${sgn(u)}U</b></td></tr>`;
  el.innerHTML = `<table class="shadow-t"><thead><tr><th>做法</th><th>笔数</th><th>合计</th></tr></thead><tbody>` +
    row("现在用的规则", "交易台上显示的就是这一套", L.n || 0, L.closed, L.total_u || 0, true) +
    sh.map((x) => row(x.name, x.why, x.n, x.closed, x.u)).join("") + `</tbody></table>` +
    `<p class="note">没采用、被换下来的做法，从${(L.frozen || "").slice(5).replace("-", "月")}日起和现行规则用同一份数据同时记账。<b>换规则的条件</b>：影子规则攒够30笔以上、明显比现行规则好，而且5年回测前后两半也都更好——到时候我会在进化日志里写出来，你同意了才换。</p>`;
}
function renderEvo(E, L) {
  const el = $("evoList"); if (!el) return;
  if (!E || !E.items) { el.innerHTML = `<li class="note">进化日志没载入。</li>`; return; }
  const SH = {}; for (const x of (L && L.shadow) || []) SH[x.key] = x;
  el.innerHTML = E.items.map((x) => { const s2 = x.shadow && SH[x.shadow];
    return `<li class="${x.kind === "采用" ? "y" : x.kind === "观察" ? "o" : "n"}"><span class="ev-h">${x.d.slice(5).replace("-", "月")}日 · <b>${x.kind}</b></span><span class="ev-t">${x.title}</span><span class="ev-w">${x.why}</span>` +
      (s2 ? `<br><span class="ev-s">影子记账：${s2.name}，${s2.n} 笔，${sgn(s2.u)}U</span>` : "") + `</li>`; }).join("");
}

// 模拟仓按规则看：每条规则模拟了多少笔、赚亏多少，和这条规则5年回测的平均比
function renderPaperRules(B) {
  const el = $("paperRules"), P = window.JSQ_PAPER; if (!el || !B || !P) return;
  const RN = { "技术面翻多": "指标转多", "跌破": "突破", "突破": "突破", "回调企稳": "回调企稳" };
  const bt = {}; for (const [si, ri, u] of B.t) { const k = GRPN(B.syms[si]) + "·" + B.rules[ri]; (bt[k] = bt[k] || []).push(u); }
  const rows = {}; for (const b of P.book) { const g = b.rule === "放量跳空" ? "美股" : GRPN(b.sym), k = g + "·" + b.rule; (rows[k] = rows[k] || { k, g, rule: b.rule, cl: [], op: [] })[b.status === "已平" ? "cl" : "op"].push(+b.u || 0); }
  const R = Object.values(rows).sort((a, b) => b.cl.length + b.op.length - a.cl.length - a.op.length);
  if (!R.length) { el.innerHTML = `<p class="note">还没有模拟单。</p>`; return; }
  const flag = [];
  const tr = R.map((r) => {
    const sc = st(r.cl), ref = bt[r.g + "·" + (RN[r.rule] || "")], sb = ref ? st(ref) : null;
    let v = "—";
    if (!sb) v = "没有可比的回测";
    else if (sc.n < 10) v = `才 ${sc.n} 笔已平，看不出来`;
    else { const z = (sc.m - sb.m) / (sb.sd / Math.sqrt(sc.n)); v = z < -1.64 ? `<b class="r">明显差于回测</b>` : z > 1.64 ? `<b class="g">好于回测</b>（多半运气）` : "和回测一致"; if (z < -1.64 && sc.n >= 15) flag.push(r.k); }
    const op = r.op.reduce((a, b) => a + b, 0);
    return `<div class="prl"><b class="prn">${r.k}</b><span class="prv"><b class="${sc.sum >= 0 ? "g" : "r"}">${sgn(sc.sum)}U</b></span>` +
      `<small class="prd">模拟仓已平 ${sc.n} 笔${sc.n ? `，每笔 ${sgn(sc.m)}U` : ""}${r.op.length ? `；持仓中 ${r.op.length} 笔，浮动 ${sgn(op)}U` : ""}。5年回测每笔 ${sb ? `${sgn(sb.m)}U（${sb.n} 笔）` : "—"}</small><span class="prj">${v}</span></div>`;
  }).join("");
  el.innerHTML = `<div class="prls">${tr}</div>` +
    `<p class="note">"判断"是拿模拟仓已平的单子和这条规则5年回测的平均比：笔数少于10笔说明不了什么；够多了还明显差于回测，说明这条规则可能失效了。` +
    (flag.length ? `<b class="bad">现在要查：${flag.join("、")}</b>——我会把它写进进化日志，先停掉这条、重新验证，你同意了才改。` : `现在没有哪条明显变差。`) + `</p>`;
}
async function initVal() {
  if (!$("valHead")) return;
  const [B, L, E] = await Promise.all([loadBalls(), loadJSON("ledger.json"), loadJSON("evolution.json")]);
  LEDGER = L; EVO = E;
  renderValHead(B, L); renderHeat(B); renderShadow(L); renderEvo(E, L);
  renderPaperRules(B); document.addEventListener("jsq-paper", () => { renderPaperRules(B); renderValHead(B, L); if ($("tab-research") && !$("tab-research").hidden) renderFwd(L, B); });
  const seg = $("mcSeg");
  if (seg) seg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; MC.m = +b.dataset.m; seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderMC(B, true); });
  const show = () => { if ($("tab-research") && !$("tab-research").hidden) { renderMC(B, false); renderFwd(L, B); } };
  document.addEventListener("jsq-tab", (e) => { if (e.detail === "research") requestAnimationFrame(show); });
  if ("ResizeObserver" in window && $("mcCv")) { let w0 = 0; new ResizeObserver(() => { const w = $("mcCv").clientWidth; if (w && Math.abs(w - w0) > 2) { w0 = w; renderMC(B, true); renderFwd(L, B); } }).observe($("mcCv")); }
  show();
}

// ---------------------------------------------------------------- 底部状态条
async function foot() {
  const el = $("sfoot"); if (!el) return;
  const live = ($("status") || {}).className || "", lt = ($("statusText") || {}).textContent || "";
  let env = "", led = "";
  try { const r = await fetch("env.json", { cache: "no-store" }); if (r.ok) { const e = await r.json(); const d = (e.us && e.us.today && e.us.today.date) || e.date || ""; env = d ? `环境数据 ${d.slice(5).replace("-", "月")}日收盘` : ""; } } catch (e) {}
  try { const r = await fetch("ledger.json", { cache: "no-store" }); if (r.ok) { const L = await r.json(); led = `规则11月10日冻结 · 记账 ${L.n || 0} 笔${L.closed ? `，已平 ${L.closed} 笔 ${sgn(L.closed_u || 0, 0)}U` : ""}`; } } catch (e) {}
  el.innerHTML = `<span class="${live.includes("live") ? "on" : ""}">行情 ${lt || "—"}</span>` + (env ? `<span>${env}</span>` : "") + (led ? `<span>${led}</span>` : "") +
    `<span>验证过的品种 12 个</span><span>数据 币安 · Dukascopy · baostock · SEC</span>`;
}

function init() {
  clock(); setInterval(clock, 1000);
  initBoards();
  const obs = new MutationObserver(() => { clearTimeout(RG.t); RG.t = setTimeout(() => updRidge(false), 500); });
  ["cardName", "cardPlan", "posOut"].forEach((id) => { const e = $(id); if (e) obs.observe(e, { childList: true, characterData: true, subtree: true }); });
  setTimeout(() => updRidge(true), 2500); setInterval(() => updRidge(false), 60e3);
  if ("ResizeObserver" in window && $("ridgeCv")) { let w0 = 0; new ResizeObserver(() => { const w = $("ridgeCv").clientWidth; if (w && Math.abs(w - w0) > 2) { w0 = w; updRidge(true); } }).observe($("ridgeCv")); }
  foot(); setInterval(foot, 120e3);
  initVal();
  setInterval(() => { const sp = document.querySelector("#sfoot span"); if (!sp) return; const live = (($("status") || {}).className || "").includes("live");
    sp.className = live ? "on" : ""; sp.textContent = "行情 " + ((($("statusText") || {}).textContent) || "—"); }, 3000);
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
