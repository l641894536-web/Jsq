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
      vb: ab ? "小市值+成长名单" : "只做小市值", vs: pc(av, 1) })
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

// A股选股方法体检（research/ashare_factor_bt.py，2021-11→2026-10，每月换仓，排前20%的比全部平均每月多涨）
// [名字, 好的方向, 近5年, 前半, 后半, 2016-21(没有就null), 牛市, 熊市]
const FAC = [
  ["小市值", "越小越好", 1.27, 1.36, 1.17, 0.69, 1.39, 1.05],
  ["换手没放大", "近一月换手比一年平均低", 0.46, 0.57, 0.35, 0.05, 0.10, 1.10],
  ["跌得多（在200日线下）", "熊市里", 0.42, 0.54, 0.30, 0.04, -0.38, 1.80],
  ["净利润增速在加快", "牛市里", 0.31, 0.27, 0.35, 0.57, 0.48, 0.01],
  ["近一月跌得多", "", 0.37, 0.30, 0.44, 0.40, -0.21, 1.37],
  ["市净率低", "", 0.43, 0.68, 0.18, 0.28, 0.32, 0.63],
  ["股息率高", "", 0.10, 0.41, -0.22, 0.22, -0.18, 0.57],
  ["净利润增速高", "", 0.01, -0.19, 0.22, 0.44, 0.27, -0.43],
  ["ROE高", "", -0.44, -0.47, -0.42, 0.17, -0.65, -0.09],
  ["一年涨得多（动量）", "", -0.66, -0.69, -0.63, 0.19, -0.41, -1.08],
];
function facBars() {
  const W = (v) => Math.min(100, Math.abs(v) / 1.5 * 50);
  return `<div class="fac">` + FAC.map((f) => `<div class="fac-r"><span class="fac-n">${f[0]}${f[1] ? `<small>${f[1]}</small>` : ""}</span>
    <span class="fac-t"><i class="fac-0"></i><i class="fac-b ${f[2] >= 0 ? "g" : "r"}" style="${f[2] >= 0 ? "left:50%" : `left:${50 - W(f[2])}%`};width:${W(f[2])}%"></i></span>
    <span class="fac-v"><b>${f[2] >= 0 ? "+" : "−"}${Math.abs(f[2]).toFixed(2)}%</b><small>牛${f[6] >= 0 ? "+" : "−"}${Math.abs(f[6]).toFixed(1)} 熊${f[7] >= 0 ? "+" : "−"}${Math.abs(f[7]).toFixed(1)}</small></span></div>`).join("") + `</div>
    <p class="note">每月初按这一条挑排前20%的股票，之后一个月比全部股票平均多涨（每月，%）。右边小字是牛市月份、熊市月份分开算。范围：成交够（日均3000万以上）、非ST、上市满一年。</p>`;
}
// A股常见交易做法体检（research/ashare_trader_bt.py，近5年，每笔扣0.3%后、先按天平均）[做法, 每笔, 前半, 后半, 2016-21, 说明]
const TRD = [
  ["打板（首板，冲到涨停价就买）", -0.89, -0.95, -0.83, -1.09, "按都能买到算；真能买到的多半是后来炸板的（那些每笔 −4.8%），封住的买不到"],
  ["连板接力（2进3以上）", -2.47, -2.57, -2.37, -2.08, "高潮阶段也是 −1.3%"],
  ["涨停次日开盘追，后天卖", -0.58, -0.71, -0.44, -0.58, "只有冰点阶段 +0.1%"],
  ["涨停回马枪（回落5%不破涨停日低点，拿5天）", -0.94, -1.13, -0.75, -1.00, "比大盘还差 0.8%"],
  ["缩量回踩20日线（拿10天）", -0.05, -0.42, 0.32, -0.24, "两段相反，没有优势"],
  ["超跌反弹（5天跌15%，拿5天）", -0.71, -0.67, -0.75, -1.56, "只有冰点阶段 +0.6%"],
  ["净利润断层（预增后高开高走，拿20天）", -2.02, -4.90, 1.36, null, "两段相反，样本448笔；没有机构评级这一条"],
  ["隔夜持股（收盘买、开盘卖，不扣费）", -0.045, -0.046, -0.044, -0.116, "A股隔夜平均是跌的"],
];
const TRD2 = [
  ["二八轮动（沪深300/中证1000每周拿强的）", "年化 −9.7%", "一直拿沪深300 −3.9%"],
  ["行业轮动（每周拿最强3个行业）", "比大盘 −9.4%/年", "追最强行业是亏的"],
  ["均线刹车（中证1000在20日线上才拿）", "年化 +4.3%、回撤 −21%", "一直拿 −2.5%、回撤 −47%"],
  ["春节红包（节前最后一天买，节后第2天卖）", "11次10次涨，平均 +2.1%", "近5年5次全涨（+1.7%~+4.5%）"],
];
function trdHTML() {
  const p2 = (v) => v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
  return TRD.map((r) => `<div class="prl"><span class="prn">${r[0]}</span><span class="prv"><b class="${r[1] < 0 ? "r" : "g"}">${p2(r[1])}</b></span>
      <span class="prd">每笔扣费后。前后两段 ${p2(r[2])}/${p2(r[3])}，2016–21 ${p2(r[4])}。${r[5]}</span></div>`).join("") +
    `<div class="trd2">${TRD2.map((r) => `<div class="pk-rule"><b>${r[0]}</b><p>${r[1]}；${r[2]}。</p></div>`).join("")}</div>
    <p class="note">日线近似：打板按"冲到涨停价就按涨停价买"，实际要排队，真正能买到的偏向后来炸板的。短线每笔按来回 0.3%（印花税+佣金+滑点）扣，ETF 按 0.05%。</p>`;
}
function nextReb() {
  const d = new Date(Date.now() + 8 * 3600e3); let y = d.getUTCFullYear(), m = d.getUTCMonth() + 1; if (m > 11) { y++; m = 0; }
  let t = new Date(Date.UTC(y, m, 1)); while (t.getUTCDay() === 0 || t.getUTCDay() === 6) t = new Date(t.getTime() + 864e5);
  return `${t.getUTCMonth() + 1}月${t.getUTCDate()}日`;
}
function aList(E) {
  if (!A) return `<p class="note">A股名单还在准备。</p>`;
  const bull = (A.regime || "").startsWith("牛");
  const SM = A.objs.filter((o) => o.sm > 0 && o.sm <= 30).sort((a, b) => a.sm - b.sm);
  const L = A.objs.filter((o) => o.pool && o.uni && o.dd != null && o.dd > -0.3 && (o.m_r || 0) > 0.3).sort((a, b) => (b.amt || 0) - (a.amt || 0));
  const BS = { 2: "第一波反弹，不算反转", 3: "深跌后已二次确认" };
  const hiTxt = (d) => d > -0.005 ? "在一年高点附近" : `离一年高点 ${pc(d)}`;
  const row = (o) => `<div class="prl"><span class="prn"><b>${esc(o.name)}</b> <span class="pk-c">${o.code} · ${esc(o.ind)}</span></span>
    <span class="prv"><b>${big(o.growth)}</b></span><span class="prd">增速比上期快 ${Math.round((o.accel || 0) * 100)} 个百分点 · ${hiTxt(o.dd)} · 日均成交 ${o.amt >= 10 ? Math.round(o.amt) : (o.amt || 0).toFixed(1)} 亿${BS[o.bs] ? " · " + BS[o.bs] : ""}</span></div>`;
  const srow = (o) => `<div class="sm-r"><span class="sm-i">${o.sm}</span><span class="sm-n"><b>${esc(o.name)}</b><small>${o.code} · ${esc(o.ind)}</small></span><span class="sm-v"><b>${o.cap != null ? o.cap.toFixed(1) : "—"}亿</b><small>${o.growth != null && o.growth < 0 ? "利润在降" : o.growth != null ? "利润在增" : ""}</small></span></div>`;
  const ew = (window.JSQ_LIVE_A && window.JSQ_LIVE_A.ew_vs != null) ? window.JSQ_LIVE_A.ew_vs : E.a.today.ew_vs_ma200, need = 1 / (1 + ew) - 1;
  const v20 = (window.JSQ_LIVE_A && window.JSQ_LIVE_A.ew_vs20 != null) ? window.JSQ_LIVE_A.ew_vs20 : E.a.today.ew_vs_ma20;
  const brakeOn = v20 != null && v20 < 0;
  const brake = v20 == null ? "" : lane({ n: "刹车", ns: "全A等权离20日线", x: 50 + Math.max(-0.06, Math.min(0.06, v20)) / 0.06 * 50, cls: brakeOn ? "dn" : "up",
      lines: [{ x: 50, em: "20日线" }], zones: [{ a: 50, b: 100, cls: "up" }], vb: brakeOn ? "清仓等站回" : "拿着", vs: pc(v20, 1) });
  const small = `<div class="pk-rule"><b>主力：小市值轮动</b><p>成交够的股票里（日均成交3000万以上、非ST、上市满一年），挑总市值最小的30只，等权买，每月第一个交易日换一次（平均换掉一半）。</p>
    <p><b>一直拿</b>：近5年年化 <b>+25%</b>（前后两段 +20%/+30%），同期沪深300 −3.9%、中证1000 −2.5%。但按每天算最大回撤 <b>−48%</b>（2024年1月2日到2月7日，五周跌掉近一半），2017、2018年各亏三成多，2026年到现在 −2.5%。</p>
    <p><b>带刹车（推荐）</b>：全A等权收盘跌破20日线就清仓，站回来再买。近5年年化 <b>+17.6%</b>，最大回撤降到 <b>−20%</b>（前后两段都在 −20%以内），2021–2026 每年：+11%、+20%、−2%、+18%、+22%、+11%。代价：一年要进出约26次；2016–21 年这样做也只有 +1.6%（大盘股行情里小市值本身不赚）。</p>
    <p>这些票单看大多利润在降、跌得深，赚的是一篮子的平均：只买最小的10只年化只剩 +13%，去掉亏损股反而降到 +18%。要做就30只一起买，用A股资金的一部分。</p></div>
    <div class="pk-lanes">${brake}</div>
    <p class="pk-k">按 ${A.date.slice(5).replace("-", "月")}日收盘的30只（总市值 ${A.small && A.small.cut30 ? A.small.cut30 + "亿" : "—"} 以下）。现在开始也行，按这份买；下次换仓：${nextReb()}，按那天前一个交易日收盘的名单换，没掉出前30的继续拿。</p>
    <div class="sm-list">${SM.slice(0, 10).map(srow).join("")}</div>${SM.length > 10 ? `<details class="pk-more"><summary>其余 ${SM.length - 10} 只</summary><div class="sm-list">${SM.slice(10).map(srow).join("")}</div></details>` : ""}`;
  const growth = bull
    ? `<div class="pk-rule"><b>补充：成长加速名单（牛市才用）</b><p>净利润增速前30%且在加快、离一年高点不到30%、近半年不是最弱的，共 ${L.length} 只。牛市里"增速在加快"每月多涨约0.5%（三段都成立），优势比小市值小得多。</p></div>`
    : `<div class="pk-rule"><b>补充：成长加速名单（现在熊市，先不用）</b><p>"增速在加快"只在牛市里有用（每月多涨约0.5%，三段都成立），熊市里没用。全A等权还要涨约 ${(need * 100).toFixed(1)}% 才回到200日线。</p></div>`;
  const timing = `<div class="pk-rule"><b>大盘时机</b><p>温度跌到20以下分批买宽基（熊市冰点之后60天平均 +5.8%）；80以上不追。小市值组合不用跟着择时：熊市也在赚，试过"熊市空仓""过热不拿"都更差。</p></div>`;
  return small + growth + `<details class="pk-more"><summary>成长加速名单 ${L.length} 只</summary>${L.slice(0, 30).map(row).join("")}</details>` + timing
    + `<details class="pk-more"><summary>A股各种选股方法体检（近5年）</summary>${facBars()}</details>`
    + `<details class="pk-more"><summary>A股常见交易做法体检：打板、接力、低吸、轮动……</summary>${trdHTML()}</details>`;
}

const RULES = [
  ["美股：直接买，分散拿", "纳指在200日线上方时，名单里的股票等权买，不用等回踩或突破：同一批股票，月初直接买之后60天 +11.1%，等创新高再买 +7.8%；一半月初一半等回踩，和直接买差不多。"],
  ["美股：单只别用均线止损", "名单股买了一直拿120天平均 +32%；跌破50日线就卖只剩 +10%（成长股来回洗得很凶）。整篮子44个月里只有5个月亏钱，全在2021年底见顶前。"],
  ["美股：风险靠大盘线管", "纳指跌破200日线就停止新买；跌到认错线（跌破那天收盘再跌15%）全卖。2021年底那几篮子最多亏32%，就是靠这条线挡长熊。"],
  ["深跌的不抄", "跌了30%以上的高成长股，之后60天平均跑输1.3%。已经套着的：第一波反弹不算反转，回踩不破前低、再涨过反弹高点才算（之后再破低的概率美股从53%降到33%，A股从45%降到28%）。查个股里能看到每只在哪一步。"],
  ["A股：别做打板、接力、追涨停、追最强行业", "近5年回测每笔都亏（打板 −0.9%、连板接力 −2.5%、涨停次日追 −0.6%、行业轮动每年少赚9%），前后两段都一样。能用的只有：小市值一篮子（带20日线刹车）、冰点分批买、春节前买节后卖。"],
  ["A股：小市值一篮子 + 大盘时机", "A股近5年：增速高、股息高基本没用，ROE高、一年涨得多反而每月跑输0.4%~0.7%。最强最稳的是小市值（每月多涨1.3%，三段都成立），其次熊市里买跌得多的、牛市里买增速在加快的。小市值要30只一起拿、每月换，别挑其中几只重仓。"],
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

// ------------------------------------------------ 验证页：正股名单记账（pages/stock_ledger.py → stock_ledger.json）
async function renderLedgerStocks() {
  const box = $("sledBox"); if (!box) return;
  const L = await getJ("stock_ledger.json");
  if (!L || !L.baskets || !L.baskets.length) { box.innerHTML = `<p class="note">从 2026-11-12 开始记，每个月第一次出数据那天按收盘价记一篮。</p>`; return; }
  const BN = { "sh.000852": "中证1000", "sh.000300": "沪深300", QQQ: "纳指QQQ" };
  const p2 = (x) => x == null ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(1) + "%";
  const rows = L.baskets.slice().reverse().map((b) => {
    const bench = Object.entries(b.bench_ret || {}).map(([k, v]) => `${BN[k] || k} ${p2(v)}`).join("、");
    const best = (b.members || []).filter((m) => m.ret != null).sort((x, y) => y.ret - x.ret);
    const ex = best.length ? `最好 ${esc(best[0].name)} ${p2(best[0].ret)}，最差 ${esc(best[best.length - 1].name)} ${p2(best[best.length - 1].ret)}` : "";
    return `<tr><td>${esc(b.kind)}<small>${b.date} 起 · ${b.members.length} 只 · ${b.closed ? "已结账" : `第 ${b.days}/20 天`}</small></td>
      <td class="n ${b.ret == null ? "" : b.ret >= 0 ? "g" : "r"}">${p2(b.ret)}</td><td>${bench || "—"}<small>${ex}</small></td></tr>`;
  }).join("");
  box.innerHTML = `<table class="shadow-t link-t"><colgroup><col style="width:38%"><col style="width:18%"><col></colgroup><thead><tr><th>名单</th><th>等权收益</th><th>对照</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note">每月第一次出数据那天按收盘价"买入"，满20个交易日结账（回测是月初开盘买、拿20天）。几个月后拿来和回测的平均（A股小市值每月比等权多 +1.3%；美股名单60天比同类多 +4.4%）对比，看规则在新数据上还灵不灵。</p>`;
  $("sledSub").textContent = L.updated ? `更新 ${L.updated.slice(5, 16).replace("T", " ")} UTC` : "";
}

function init() {
  renderLink();
  renderLedgerStocks();
  const go = () => { if (!US && !A) loadAll(); else renderPick(); };
  if (window.JSQ_ENV) go();
  document.addEventListener("jsq-env-ready", go);
  document.addEventListener("jsq-live", () => { if (US || A) renderPick(); });
}
init();
})();
