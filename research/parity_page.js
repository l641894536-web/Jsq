// 用本地 Chrome 打开实时版页面（行情用 11月6日收盘时的真实数据代替网络），截手机尺寸的图
const { chromium } = require("/opt/npm-tools/node_modules/playwright");
const fs = require("fs");
const SITE = "/home/claude/site";
const FX = JSON.parse(fs.readFileSync("/home/claude/shot/fx.json", "utf8"));
const Q = JSON.parse(fs.readFileSync("/tmp/fake_quotes.json", "utf8"));
const LWC = fs.readFileSync("/home/claude/shot/node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js", "utf8");
const BASE = "https://l641894536-web.github.io/Jsq/";

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: "zh-CN", timezoneId: "Asia/Shanghai" });
  await ctx.addInitScript(() => {
    try { localStorage.setItem("jsq.tf", "1h"); localStorage.setItem("jsq.sym", "XAUUSDT"); localStorage.setItem("tab", "contract");
      localStorage.setItem("jsq.pos.AMDUSDT", JSON.stringify({ side: 1, E: "424.36", S: "439", N: "543.77" }));
      localStorage.setItem("jsq.pos.MUUSDT", JSON.stringify({ side: 1, E: "620", S: "600", N: "500" }));
      localStorage.setItem("jsq.pos.BTCUSDT", JSON.stringify({ side: -1, E: "77000", S: "", N: "" }));
      localStorage.setItem("jsq.acct", "3200"); } catch (e) {}
    window.WebSocket = class { constructor() { this.readyState = 0; } close() {} send() {} };
  });
  await ctx.route("**/*", async (route) => {
    const u = route.request().url();
    const json = (o) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(o) });
    if (u === BASE || u.startsWith(BASE + "index.html") || u.startsWith(BASE + "#")) return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: fs.readFileSync(`${SITE}/index.html`) });
    for (const f of ["env.json", "env_static.json", "snapshot.json", "icon-180.png"]) if (u.startsWith(BASE + f)) return route.fulfill({ status: 200, body: fs.readFileSync(`${SITE}/${f}`), contentType: f.endsWith(".png") ? "image/png" : "application/json" });
    if (u.includes("lightweight-charts")) return route.fulfill({ status: 200, contentType: "application/javascript", body: LWC });
    if (u.includes("fonts.googleapis") || u.includes("fonts.gstatic")) return route.fulfill({ status: 200, contentType: "text/css", body: "" });
    if (u.includes("fapi.binance.com")) {
      let m = /klines\?symbol=(\w+)&interval=(\w+)/.exec(u);
      if (m) { const k = FX[`${m[1]}|${m[2] === "1d" ? "1d" : "1h"}`]; return k ? json(k) : route.fulfill({ status: 400, body: "{}" }); }
      if (/ticker\/price$/.test(u.split("?")[0]) && !u.includes("symbol=")) return json(Object.keys(FX).filter((k) => k.endsWith("|1h")).map((k) => ({ symbol: k.split("|")[0], price: FX[k][FX[k].length - 1][4] })));
      m = /ticker\/price\?symbol=(\w+)/.exec(u);
      if (m) { const k = FX[`${m[1]}|1h`]; return json({ symbol: m[1], price: k ? k[k.length - 1][4] : "0" }); }
      if (u.includes("ticker/24hr")) {
        const one = (s) => { const k = FX[`${s}|1h`]; if (!k) return null; const last = +k[k.length - 1][4], open = +k[k.length - 25][4]; return { symbol: s, lastPrice: String(last), openPrice: String(open), priceChangePercent: String(((last / open - 1) * 100).toFixed(2)) }; };
        m = /symbol=(\w+)/.exec(u);
        return json(m ? one(m[1]) : Object.keys(FX).filter((k) => k.endsWith("|1h")).map((k) => one(k.split("|")[0])).filter(Boolean));
      }
      if (u.includes("premiumIndex")) return json({ symbol: "X", markPrice: "1", lastFundingRate: "0.00010000", nextFundingTime: Date.now() + 2.5 * 3600e3 });
      return route.fulfill({ status: 404, body: "{}" });
    }
    if (u.includes("qt.gtimg.cn")) {
      const q = decodeURIComponent(u.split("q=")[1] || "");
      const lines = q.split(",").map((c) => {
        if (c === "sh000001") { const f = new Array(50).fill("0"); f[30] = "20261106150000"; return `v_sh000001="${f.join("~")}";`; }
        const k = c.replace(/^s_/, ""); return Q[k] ? `v_s_${k}="${Q[k]}";` : "";
      });
      return route.fulfill({ status: 200, contentType: "application/javascript", body: lines.join("\n") });
    }
    return route.abort();
  });
  const page = await ctx.newPage();
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  await page.goto(BASE, { waitUntil: "load" });
  await page.waitForTimeout(4000);
  const clipTo = async (sel, extra = 12) => { const b = await page.locator(sel).boundingBox(); return b ? b.y + b.height + extra : 1600; };
  const shot = async (name, sel1, sel2, pad = 8) => {
    const a = await page.locator(sel1).boundingBox(), b = await page.locator(sel2 || sel1).boundingBox();
    const y = Math.max(0, a.y - pad), h = b.y + b.height - y + pad;
    await page.screenshot({ path: `/home/claude/shot/${name}.png`, clip: { x: 0, y, width: 390, height: Math.min(h, 3000) }, fullPage: true });
  };
  await page.waitForTimeout(9000);
  const out = await page.evaluate(async () => {
    const o = {};
    for (const s of ["BTCUSDT", "XAUUSDT", "AMDUSDT"]) {
      await window.JSQ_NEEDD1(s);
      for (const [sd, k] of [[1, "l"], [-1, "s"]]) { o[s.slice(0, 3) + k] = window.JSQ_BRK(s, sd); o[s.slice(0, 3) + k + "_tech"] = window.JSQ_BRK(s, sd, "tech"); }
    }
    return o;
  });
  require("fs").writeFileSync("/tmp/js_trades.json", JSON.stringify(out));
  console.log("errors:", errs.slice(0, 5));
  await browser.close();
})();
