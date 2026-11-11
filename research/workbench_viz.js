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
  foot(); setInterval(foot, 30e3);
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
