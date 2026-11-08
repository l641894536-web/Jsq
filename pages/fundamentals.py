"""基本面数据（给交易台"正股：发展空间 / 选股"用），写到 fund 分支。

- A股季度成长与盈利（baostock，2020Q1 起）：
    a_share/growth.csv.xz  code, year, quarter, pubDate, statDate, YOYEquity, YOYAsset, YOYNI, YOYEPSBasic, YOYPNI
    a_share/profit.csv.xz  code, year, quarter, pubDate, statDate, roeAvg, npMargin, gpMargin, netProfit, epsTTM, MBRevenue, totalShare, liqaShare
    a_share/state.csv      每个 (code, year, quarter) 是否已查过、查到没有（没查到的最近两个季度每次重查）
  从最近的季度往前补，时间用完就停，下次接着补（回测用 pubDate 做时点，避免偷看）。
- 美股财报日（yfinance，币安有股票合约的那些美股）：us/earnings.csv  ticker, date, eps_est, eps_act, surprise_pct

用法: python pages/fundamentals.py --out <fund 目录> --status <data 分支 status.json> --minutes 300 [--flag continue.flag]
时间用完还没补完时写出 --flag 文件，工作流据此再触发一次。
"""
import argparse, contextlib, datetime as dt, io, json, os, sys, time
from pathlib import Path
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True); ap.add_argument("--status", default=None)
ap.add_argument("--minutes", type=float, default=300); ap.add_argument("--flag", default=None)
ap.add_argument("--start-year", type=int, default=2020)
args = ap.parse_args()
OUT = Path(args.out); (OUT / "a_share").mkdir(parents=True, exist_ok=True); (OUT / "us").mkdir(parents=True, exist_ok=True)
deadline = time.time() + args.minutes * 60
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ 美股财报日
def us_earnings():
    try:
        import yfinance as yf
    except Exception as e:
        log("yfinance missing", e); return
    tickers = []
    if args.status and os.path.exists(args.status):
        st = json.load(open(args.status))
        tickers = sorted({p.replace("USDT", "") for p in st.get("stages", {}).get("binance", {}).get("stock_perps", [])})
    tickers = [t for t in tickers if t.isalpha()] or ["AMD", "MU", "DELL", "NVDA", "TSLA", "AAPL", "MSFT", "GOOGL", "META", "AMZN"]
    rows, bad = [], 0
    for t in tickers:
        try:
            df = yf.Ticker(t).get_earnings_dates(limit=12)
            if df is None or df.empty:
                bad += 1; continue
            for idx, r in df.iterrows():
                rows.append(dict(ticker=t, date=str(pd.Timestamp(idx).tz_convert("America/New_York").date()) if pd.Timestamp(idx).tzinfo else str(pd.Timestamp(idx).date()),
                                 eps_est=r.get("EPS Estimate"), eps_act=r.get("Reported EPS"), surprise_pct=r.get("Surprise(%)")))
        except Exception as e:
            bad += 1; log("earnings fail", t, str(e)[:120])
        time.sleep(0.4)
    if rows:
        pd.DataFrame(rows).drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"]).to_csv(OUT / "us" / "earnings.csv", index=False)
    log(f"us earnings: {len(tickers)} tickers, {len(rows)} rows, {bad} failed")


# ------------------------------------------------------------------ A股成长/盈利
def a_share():
    import baostock as bs

    def login():
        for i in range(5):
            with contextlib.redirect_stdout(io.StringIO()):
                lg = bs.login()
            if lg.error_code == "0":
                return True
            time.sleep(2 + 3 * i)
        return False

    def q(fn, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            rs = fn(**kw)
        if rs.error_code != "0":
            raise RuntimeError(f"{rs.error_code} {rs.error_msg}")
        rows = []
        while (rs.error_code == "0") & rs.next():
            rows.append(rs.get_row_data())
        return rows, list(rs.fields)

    if not login():
        log("baostock login failed"); return False
    basic, f = q(bs.query_stock_basic)
    basic = pd.DataFrame(basic, columns=f)
    codes = sorted(basic[(basic.type == "1") & (basic.status == "1")].code)
    today = dt.date.today()
    last_q = (today.month - 1) // 3          # 上一个已结束的季度
    y_end, q_end = (today.year, last_q) if last_q > 0 else (today.year - 1, 4)
    quarters = [(y, qq) for y in range(args.start_year, y_end + 1) for qq in range(1, 5) if (y, qq) <= (y_end, q_end)][::-1]
    recent = set(quarters[:2])
    stp = OUT / "a_share" / "state.csv"
    state = pd.read_csv(stp, dtype={"code": str}) if stp.exists() else pd.DataFrame(columns=["code", "year", "quarter", "found"])
    done = {(r.code, int(r.year), int(r.quarter)) for r in state.itertuples() if not ((int(r.year), int(r.quarter)) in recent and int(r.found) == 0)}
    files = {"growth": OUT / "a_share" / "growth.csv.xz", "profit": OUT / "a_share" / "profit.csv.xz"}
    old = {k: (pd.read_csv(p, dtype=str) if p.exists() else None) for k, p in files.items()}
    new = {"growth": [], "profit": []}; fields = {}; st_new = []
    calls, t0, complete = 0, time.time(), True

    def save():
        for k in files:
            if not new[k] and old[k] is None:
                continue
            d = pd.DataFrame(new[k], columns=fields.get(k)) if new[k] else None
            allp = pd.concat([x for x in (old[k], d) if x is not None], ignore_index=True)
            allp = allp.drop_duplicates(["code", "statDate"], keep="last")
            allp.to_csv(files[k], index=False)
        s2 = pd.concat([state, pd.DataFrame(st_new, columns=["code", "year", "quarter", "found"])], ignore_index=True)
        s2.drop_duplicates(["code", "year", "quarter"], keep="last").to_csv(stp, index=False)

    for (y, qq) in quarters:
        todo = [c for c in codes if (c, y, qq) not in done]
        if not todo:
            continue
        log(f"{y}Q{qq}: {len(todo)} to fetch")
        for c in todo:
            if time.time() > deadline:
                complete = False; break
            found = 0
            for k, fn in (("growth", bs.query_growth_data), ("profit", bs.query_profit_data)):
                for attempt in range(3):
                    try:
                        rows, fl = q(fn, code=c, year=y, quarter=qq)
                        fields[k] = fl; new[k].extend(rows); found = found or int(bool(rows)); break
                    except Exception as e:
                        time.sleep(1 + attempt); login()
                calls += 1
            st_new.append((c, y, qq, found))
            if calls % 2000 == 0:
                save(); log(f"  {calls} calls, {calls / (time.time() - t0):.1f}/s")
        if not complete:
            break
    save()
    with contextlib.redirect_stdout(io.StringIO()):
        bs.logout()
    log(f"a_share fundamentals: {calls} calls in {time.time() - t0:.0f}s, complete={complete}")
    return complete


us_earnings()
ok = a_share()
if not ok and args.flag:
    Path(args.flag).write_text("continue")
