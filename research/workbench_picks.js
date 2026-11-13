(() => {
"use strict";
// 正股页：现在买什么（美股成长名单 / A股观察名单）+ 美股和A股的关联（2026-11-13）
// 数据：stocks_us.json（pages/stocks_us.py）、stocks_a.json（env_pipeline）；关联数字来自 research/us_cn_link_bt.py
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pc = (x, d = 0) => x == null || !isFinite(x) ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(d) + "%";
const big = (x) => x == null || !isFinite(x) ? "—" : (x >= 0 ? "+" : "−") + (Math.abs(x) >= 10 ? Math.round(Math.abs(x) * 100) + "%" : Math.abs(x * 100).toFixed(0) + "%");
const px = (x) => x == null ? "—" : x >= 100 ? x.toFixed(1) : x.toFixed(2);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const REST = "https://fapi.binance.com";
let US = null, A = null, LIVE = {};

function getJ(u) { return fetch(u + "?d=" + new Date().toISOString().slice(0, 10)).then((r) => r.ok ? r.json() : null).catch(() => null); }
function objs(d) { if (!d) return null; const F = d.fields; d.objs = d.rows.map((r) => Object.fromEntries(F.map((k, i) => [k, r[i]]))); return d; }

// 一条跑道：x 是 0–100 的位置
function lane({ n, ns, x, cls = "", lines = [], zones = [], vb, vs, note, x2 }) {
  const L = lines.map((l) => `<i class="ln-l ${l.cls || ""}" style="left:${clamp(l.x, 0, 100)}%">${l.em ? `<em>${esc(l.em)}</em>` : ""}</i>`).join("");
  const Z = zones.map((z) => `<i class="ln-z ${z.cls}" style="left:${clamp(z.a, 0, 100)}%;width:${clamp(z.b, 0, 100) - clamp(z.a, 0, 100)}%"></i>`).join("");
  const D2 = x2 == null ? "" : `<i class="ln-dot past" style="left:${clamp(x2, 0, 100)}%"></i>`;
  return `<div class="lane nolink"><span class="ln-n"><b>${esc(n)}</b>${ns ? `<small>${esc(ns)}</small>` : ""}</span>
    <span class="ln-t">${Z}${L}${D2}<i class="ln-dot ${cls}" style="left:${clamp(x, 0, 100)}%"></i></span>
    <span class="ln-v"><b>${vb}</b>${vs ? `<small>${vs}</small>` : ""}</span>${note ? `<span class="ln-note">${note}</span>` : ""}</div>`;
}

// ------------------------------------------------ 现在买什么
function regimeLanes(E) {
  const u = E.us.today, a = E.a.today, AL = window.JSQ_LIVE_A;
  const ux = (v) => 50 + clamp(v, -0.15, 0.15) / 0.15 * 50;
  const uv = u.ndx_vs, av = AL && AL.ew_vs != null ? AL.ew_vs : a.ew_vs_ma200, t = AL ? AL.temp : a.temp;
  const ub = uv >= 0, ab = av >= 0;
  return lane({ n: "美股", ns: "纳指离200日线", x: ux(uv), cls: ub ? "up" : "dn", lines: [{ x: 50, em: "200日线" }], zones: [{ a: 50, b: 100, cls: "up" }],
      vb: ub ? "可以买" : "停止新买", vs: pc(uv, 1), note: ub ? "" : `跌到认错线 ${Math.round(u.stop_line)} 就全卖` })
    + lane({ n: "A股", ns: "全A等权离200日线", x: ux(av), cls: ab ? "up" : "dn", lines: [{ x: 50, em: "200日线" }], zones: [{ a: 50, b: 100, cls: "up" }],
      vb: ab ? "按名单买" : "先不买个股", vs: pc(av, 1) })
    + lane({ n: "A股温度", ns: "20以下冰点", x: t, cls: t < 20 ? "up go" : t > 80 ? "dn" : "", lines: [{ x: 20, em: "20" }, { x: 80, em: "80" }], zones: [{ a: 0, b: 20, cls: "up" }],
      vb: t < 20 ? "分批买宽基" : t > 80 ? "别追" : "等", vs: String(Math.round(t)) });
}

function usLanes() {
  if (!US) return `<p class="note">美股名单还在准备。</p>`;
  const P = US.objs.filter((o) => o.pick === 2), W = US.objs.filter((o) => o.pick === 1);
  const x = (dd) => (clamp(dd, -0.6, 0) + 0.6) / 0.6 * 100;
  const row = (o, ok) => {
    const lp = LIVE[o.t] && Math.abs(LIVE[o.t] / o.px - 1) < 0.25 ? LIVE[o.t] : null;   // 合约价和收盘差太多就不用（防代码对不上）
    const cur = lp || o.px, hi = o.need / 0.7, dd = cur / hi - 1, gap = o.need / cur - 1;
    const near = !ok && gap > 0 && gap < 0.05;
    const growth = `营收${big(o.rev)} 净利${big(o.ni)}`;
    let note = growth;
    if (!ok) {
      if (dd > -0.3 && o.m_r <= 0.3) note += `。近半年太弱（排后30%），等它不再是最弱的那批`;
      else if (gap <= 0) note += `。现价已回到 ${px(o.need)} 上方，收盘站住、下次更新名单时就会进来`;
      else note += `。回到 <b>${px(o.need)}</b> 以上才算（还差 ${pc(gap, 1)}）`;
    }
    return lane({ n: o.t, ns: (o.name || "").split(" ")[0], x: x(dd), cls: ok ? "up" : near ? "near" : "past",
      lines: [{ x: 50, em: "−30%" }], zones: [{ a: 50, b: 100, cls: "up" }],
      vb: px(cur), vs: `离高点 ${pc(dd)}`, note });
  };
  const head = `<p class="pk-k"><b class="ok">可以买 ${P.length} 只</b>：营收和净利润增速都在前30%、离一年高点不到30%、近半年不是最弱的。</p>`;
  const L1 = P.length ? P.map((o) => row(o, true)).join("") : `<p class="note">现在没有同时满足的股票。</p>`;
  const L2 = W.length ? `<p class="pk-k">成长够了、但跌太多或太弱的 ${W.length} 只（先别买，跌了30%以上的高成长股之后60天反而跑输 1.3%）：</p>` +
    W.sort((a, b) => (a.need / (LIVE[a.t] || a.px)) - (b.need / (LIVE[b.t] || b.px))).map((o) => row(o, false)).join("") : "";
  const src = Object.keys(LIVE).length ? "价格是币安合约实时价" : `价格是 ${US.date} 收盘`;
  return head + `<div class="pk-lanes">${L1}</div>` + (L2 ? `<details class="pk-more"><summary>${W.length} 只等回到线上的（最近的 ${W.slice(0, 3).map((o) => o.t).join("、")}）</summary><div class="pk-lanes">${L2}</div></details>` : "")
    + `<p class="note">跑道：左边 = 比一年高点低60%，右边 = 一年高点；竖线 = 低30%。${src}。范围是币安上有合约的约 ${US.n_uni} 只美股，财报只用公告之后的。</p>`;
}

function aList(E) {
  if (!A) return `<p class="note">A股名单还在准备。</p>`;
  const bull = (A.regime || "").startsWith("牛");
  const L = A.objs.filter((o) => o.pool && o.uni && o.dd != null && o.dd > -0.3 && (o.m_r || 0) > 0.3).sort((a, b) => (b.amt || 0) - (a.amt || 0));
  const BS = { 2: "第一波反弹，不算反转", 3: "深跌后已二次确认" };
  const hiTxt = (d) => d > -0.005 ? "在一年高点附近" : `离一年高点 ${pc(d)}`;
  const row = (o) => `<div class="prl"><span class="prn"><b>${esc(o.name)}</b> <span class="pk-c">${o.code} · ${esc(o.ind)}</span></span>
    <span class="prv"><b>${big(o.growth)}</b></span><span class="prd">增速比上期快 ${Math.round((o.accel || 0) * 100)} 个百分点 · ${hiTxt(o.dd)} · 日均成交 ${o.amt >= 10 ? Math.round(o.amt) : (o.amt || 0).toFixed(1)} 亿${BS[o.bs] ? " · " + BS[o.bs] : ""}</span></div>`;
  const ew = (window.JSQ_LIVE_A && window.JSQ_LIVE_A.ew_vs != null) ? window.JSQ_LIVE_A.ew_vs : E.a.today.ew_vs_ma200, need = 1 / (1 + ew) - 1;
  const head = bull
    ? `<p class="pk-k"><b class="ok">A股是牛市：按名单买</b>（净利润增速前30%且在加快、离一年高点不到30%、近半年不是最弱的），共 ${L.length} 只。牛市里这类股票之后60天平均跑赢全市场约 0.9%，优势不大，要分散。</p>`
    : `<p class="pk-k"><b class="warn">A股是熊市：先不买个股</b>。回测里成长股在A股熊市不跑赢（−0.1%/60天）；能做的是温度跌到20以下时分批买宽基（熊市冰点之后60天平均 +5.8%，73%上涨）。全A等权还要涨约 ${(need * 100).toFixed(1)}% 才回到200日线，到时再按下面的名单买。</p>`;
  const N = 8;
  return head + `<p class="pk-k">${bull ? "名单" : "转牛后用的名单"}（${L.length} 只，右边是净利润同比，按成交额排）：</p>` + L.slice(0, N).map(row).join("")
    + (L.length > N ? `<details class="pk-more"><summary>其余 ${L.length - N} 只</summary>${L.slice(N).map(row).join("")}</details>` : "");
}

const RULES = [
  ["美股：直接买，分散拿", "纳指在200日线上方时，名单里的股票等权买，不用等回踩或突破：同一批股票，月初直接买之后60天 +11.1%，等创新高再买 +7.8%；一半月初一半等回踩，和直接买差不多。"],
  ["美股：单只别用均线止损", "名单股买了一直拿120天平均 +32%；跌破50日线就卖只剩 +10%（成长股来回洗得很凶）。整篮子44个月里只有5个月亏钱，全在2021年底见顶前。"],
  ["美股：风险靠大盘线管", "纳指跌破200日线就停止新买；跌到认错线（跌破那天收盘再跌15%）全卖。2021年底那几篮子最多亏32%，就是靠这条线挡长熊。"],
  ["深跌的不抄", "跌了30%以上的高成长股，之后60天平均跑输1.3%。已经套着的：第一波反弹不算反转，回踩不破前低、再涨过反弹高点才算（之后再破低的概率美股从53%降到33%，A股从45%降到28%）。查个股里能看到每只在哪一步。"],
  ["A股：先看大盘，再挑股", "A股熊市里挑股票没优势；温度跌到20以下分批买宽基，80以上不追。牛市里按名单买，优势只有约0.9%/60天，要分散、别重仓一只。"],
];

function renderPick() {
  const E = window.JSQ_ENV; if (!E || !$("pickPanel")) return;
  $("pickSub").textContent = `${US ? US.date : E.us.today.date} 收盘 · 财报按公告日`;
  $("pickRegime").innerHTML = regimeLanes(E);
  $("pickUS").innerHTML = usLanes();
  $("pickA").innerHTML = aList(E);
  $("pickRules").innerHTML = RULES.map(([k, v]) => `<div class="pk-rule"><b>${k}</b><p>${v}</p></div>`).join("");
}

// ------------------------------------------------ 美股和A股的关联（research/us_cn_link_bt.py，2021-11 → 2026-11）
// [美股, A股跟随, 跳空相关, 开盘后相关, 大涨夜跳空, 大涨夜开盘后(比平常), 大跌夜跳空, 大跌夜开盘后(比平常)]
const LINK = [
  ["纳指100", "A股指数", 0.42, -0.04, 0.0040, -0.0008, -0.0067, 0.0017],
  ["半导体", "A股半导体", 0.38, -0.04, 0.0105, -0.0039, -0.0113, 0.0025],
  ["英伟达", "光模块/PCB", 0.39, 0.01, 0.0113, -0.0031, -0.0145, 0.0001],
  ["AMD", "通富/海光", 0.28, -0.02, 0.0153, -0.0016, -0.0121, -0.0015],
  ["美光", "存储", 0.37, -0.04, 0.0162, -0.0045, -0.0144, 0.0055],
  ["苹果", "果链", 0.36, -0.01, 0.0082, 0.0021, -0.0082, 0.0020],
  ["特斯拉", "汽车链", 0.36, -0.03, 0.0085, -0.0029, -0.0077, 0.0005],
  ["中概股", "A股指数", 0.41, 0.00, 0.0058, -0.0004, -0.0056, 0.0011],
  ["黄金", "金矿股", 0.58, -0.07, 0.0147, -0.0004, -0.0173, 0.0045],
  ["铜", "铜矿股", 0.47, 0.01, 0.0115, 0.0005, -0.0144, -0.0044],
  ["原油", "石油股", 0.54, 0.04, 0.0100, -0.0012, -0.0148, -0.0029],
];
const MEMB = { "A股指数": "沪深300、创业板指、中证1000、上证", "A股半导体": "北方华创、中微、中芯、寒武纪、兆易、澜起", "光模块/PCB": "中际旭创、新易盛、工业富联、沪电、胜宏、天孚",
  "通富/海光": "通富微电、海光信息", "存储": "兆易创新、江波龙、佰维存储、澜起科技", "果链": "立讯精密、歌尔、蓝思、鹏鼎", "汽车链": "拓普、三花、比亚迪、宁德时代",
  "金矿股": "紫金、山东黄金、中金黄金", "铜矿股": "江西铜业、紫金、洛阳钼业", "石油股": "中国海油、中国石油" };

function renderLink() {
  if (!$("linkLanes")) return;
  const x = (c) => (clamp(c, -0.1, 0.7) + 0.1) / 0.8 * 100;
  $("linkLanes").innerHTML = `<div class="link-key"><span><i class="k-on"></i>开盘跳空跟美股</span><span><i class="k-off"></i>开盘以后跟美股</span></div>` +
    LINK.map((r) => lane({ n: r[0], ns: "→ " + r[1], x: x(r[2]), x2: x(r[3]), cls: "", lines: [{ x: x(0), em: "0", cls: "f" }, { x: x(0.5), em: "0.5", cls: "f" }],
      vb: r[2].toFixed(2), vs: `开盘后 ${r[3] >= 0 ? "+" : "−"}${Math.abs(r[3]).toFixed(2)}` })).join("");
  const p2 = (v) => Math.abs(v) < 0.0005 ? "0.0%" : (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(1) + "%";
  const cl = (v) => Math.abs(v) < 0.0005 ? "n" : v < 0 ? "n r" : "n g";
  $("linkTable").innerHTML = `<table class="shadow-t link-t"><colgroup><col style="width:40%"><col><col><col><col></colgroup>
    <thead><tr><th rowspan="2">美股 → A股</th><th colspan="2">美股大涨那晚</th><th colspan="2">美股大跌那晚</th></tr><tr><th>跳空</th><th>开盘后</th><th>跳空</th><th>开盘后</th></tr></thead><tbody>` +
    LINK.map((r) => `<tr><td>${r[0]} → ${r[1]}<small>${MEMB[r[1]] || ""}</small></td><td class="n">${p2(r[4])}</td><td class="${cl(r[5])}">${p2(r[5])}</td><td class="n">${p2(r[6])}</td><td class="${cl(r[7])}">${p2(r[7])}</td></tr>`).join("") + `</tbody></table>
    <p class="note">大涨夜/大跌夜 = 美股这段涨跌排在近5年前10%/后10%（纳指约 ±1.7%，英伟达约 +4%/−3.6%）。"开盘后"是比平常日子多出来的部分，每条只有118天，统计上大多不显著（t 值绝对值 &lt; 2）。</p>`;
}

async function loadAll() {
  const [u, a] = await Promise.all([getJ("stocks_us.json"), getJ("stocks_a.json")]);
  US = objs(u); A = objs(a);
  renderPick();
  if (US) {   // 币安合约实时价（这些股票都有币安合约）
    fetch(REST + "/fapi/v1/ticker/price").then((r) => r.ok ? r.json() : []).then((arr) => {
      const want = new Set(US.objs.filter((o) => o.pick).map((o) => o.t + "USDT"));
      for (const z of arr || []) if (want.has(z.symbol)) LIVE[z.symbol.slice(0, -4)] = +z.price;
      if (Object.keys(LIVE).length) renderPick();
    }).catch(() => {});
  }
}

function init() {
  renderLink();
  const go = () => { if (!US && !A) loadAll(); else renderPick(); };
  if (window.JSQ_ENV) go();
  document.addEventListener("jsq-env-ready", go);
  document.addEventListener("jsq-live", () => { if (US || A) renderPick(); });
}
init();
})();
