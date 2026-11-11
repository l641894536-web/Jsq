"""账户层面风控回测：把交易台现行规则近5年的每一笔信号放进一个 3200U 的账户里一起跑。
每笔 100U 保证金开5倍（持仓价值500U）。看：同时最多几笔、最大回撤、最差一天/一周、哪些品种一起亏；
再比较几条账户规则：同时持仓上限、同一组（7个币 / 3只股票 / 金银）上限、当周亏到多少停手。
规则单子来源：indicator_trades.csv.gz（突破、技术面翻多）+ dip_clean_bt.py（回调企稳）。
"""
import sys, io, contextlib
import numpy as np, pandas as pd

ACCT, NOTIONAL = 3200.0, 500.0
t = pd.read_csv("indicator_trades.csv.gz", parse_dates=["ts", "exit_ts"])
B, K = "参照：现在的突破规则", "综合分翻多/翻空(≥2项净多)"
ok = (((t.grp.isin(["黄金", "白银"])) & (t.sig == B) & (t.env == "bull") & (t.dir == "long")) |
      ((t.grp == "主流币") & (t.sig == B) & (((t.env == "bull") & (t.dir == "long")) | ((t.env == "bear") & (t.dir == "short")))) |
      ((t.grp == "主流币") & (t.sig == K) & (t.env == "bull") & (t.dir == "long")) |
      ((t.grp == "AMD/美光/戴尔") & (t.sig.isin([B, K])) & (t.env == "bull") & (t.dir == "long")))
T = t[ok][["ts", "exit_ts", "sym", "grp", "sig", "dir", "u", "R_pct"]].copy()
T["rule"] = np.where(T.sig == B, "突破", "指标转多")
# 回调企稳（熊市、纳指前一天在跌；牛市、纳指整体回调）
src = open("dip_clean_bt.py", encoding="utf8").read().split("T = pd.DataFrame(rows)")[0]
src = src.replace("pnl=pnl, half=", "pnl=pnl, exit_ts=ts[min(e, N - 1)], stopd=1 - lowest * np.exp(-0.3 * s) / c[k], half=")
g = {"__name__": "x"}; old = sys.argv; sys.argv = ["dip_clean_bt.py"]
with contextlib.redirect_stdout(io.StringIO()): exec(src, g)
sys.argv = old
D = pd.DataFrame(g["rows"])
D = D[((D.env == "熊市") & (D.up == 0)) | ((D.env == "牛市") & (D.ndip == 1))]
print("回调企稳单子", len(D), "pnl 平均", round(D.pnl.mean(), 4), "→ 需确认单位")
D2 = pd.DataFrame({"ts": pd.to_datetime(D.ts, utc=True), "exit_ts": pd.to_datetime(D.exit_ts, utc=True), "sym": D.sym, "grp": "AMD/美光/戴尔", "sig": "dip",
                   "dir": "long", "u": D.pnl, "R_pct": D.stopd, "rule": "回调企稳"})
T["ts"] = pd.to_datetime(T.ts, utc=True); T["exit_ts"] = pd.to_datetime(T.exit_ts, utc=True)
A = pd.concat([T, D2]).sort_values("ts").reset_index(drop=True)
A["G"] = A.grp.map({"黄金": "金银", "白银": "金银", "主流币": "币", "AMD/美光/戴尔": "股票"})
A.to_csv("risk_trades.csv.gz", index=False)
yrs = (A.ts.max() - A.ts.min()).days / 365.25
print(f"\n规则单子共 {len(A)} 笔，{yrs:.1f} 年，每年约 {len(A)/yrs:.0f} 笔；按组：", A.groupby("G").u.agg(["size", "mean", "sum"]).round(1).to_dict("index"))


def run(A, cap=None, gcap=None, wstop=None, risk_pct=None, max_not=2500.0, label=""):
    open_, eq, rows, wk_loss, cur_wk = [], 0.0, [], 0.0, None      # open_: (exit_ts, G, u, risk)
    taken = 0; maxc = 0; maxg = {}; maxrisk = 0.0
    for r in A.itertuples():
        # 先结算到期的
        open_.sort(key=lambda x: x[0])
        while open_ and open_[0][0] <= r.ts:
            x = open_.pop(0); eq += x[2]; rows.append((x[0], x[2]))
            wk = x[0].isocalendar()[:2]
            if wk != cur_wk: cur_wk, wk_loss = wk, 0.0
            wk_loss += x[2]
        wk = r.ts.isocalendar()[:2]
        if wk != cur_wk: cur_wk, wk_loss = wk, 0.0
        if cap and len(open_) >= cap: continue
        if gcap and sum(1 for x in open_ if x[1] == r.G) >= gcap.get(r.G, 99): continue
        if wstop and wk_loss <= -wstop: continue
        k = 1.0
        if risk_pct: k = min(max_not, (ACCT * risk_pct) / max(r.R_pct, 0.002)) / NOTIONAL
        open_.append((r.exit_ts, r.G, r.u * k, r.R_pct * NOTIONAL * k)); taken += 1
        maxc = max(maxc, len(open_)); maxrisk = max(maxrisk, sum(x[3] for x in open_))
        for g_ in ("币", "股票", "金银"): maxg[g_] = max(maxg.get(g_, 0), sum(1 for x in open_ if x[1] == g_))
    for x in open_: rows.append((x[0], x[2]))
    P = pd.Series([u for _, u in rows], index=pd.DatetimeIndex([d for d, _ in rows])).sort_index()
    cum = P.cumsum(); dd = (cum - cum.cummax()).min()
    day = P.resample("1D").sum(); wk = P.resample("W").sum(); mo = P.resample("ME").sum()
    mid = P.index[0] + (P.index[-1] - P.index[0]) / 2
    return dict(规则=label, 笔数=taken, 合计U=round(P.sum()), 年化pct=round(P.sum() / yrs / ACCT * 100, 1), 最大回撤U=round(dd), 回撤pct=round(dd / ACCT * 100, 1),
                收益回撤比=round(P.sum() / yrs / -dd, 2), 最差一天U=round(day.min()), 最差一周U=round(wk.min()), 最差一月U=round(mo.min()), 亏钱的月pct=round((mo < 0).mean() * 100),
                最多同时=maxc, 币=maxg.get("币"), 股票=maxg.get("股票"), 金银=maxg.get("金银"), 全部止损同时打到U=round(maxrisk),
                前半U=round(P[P.index < mid].sum()), 后半U=round(P[P.index >= mid].sum())), P


res = []
base, P0 = run(A, label="现在：来信号就做，每笔100U×5倍"); res.append(base)
for c in (4, 6, 8, 10): res.append(run(A, cap=c, label=f"最多同时{c}笔")[0])
for gc in ({"币": 2, "股票": 2, "金银": 2}, {"币": 3, "股票": 2, "金银": 2}, {"币": 4, "股票": 3, "金银": 2}):
    res.append(run(A, gcap=gc, label="每组上限 币%d 股%d 金银%d" % (gc["币"], gc["股票"], gc["金银"]))[0])
for w in (64, 96, 160): res.append(run(A, wstop=w, label=f"当周已亏{w}U（{w/32:.0f}%）就停到下周")[0])
for rp in (0.005, 0.01): res.append(run(A, risk_pct=rp, label=f"按止损距离定仓位：每笔最多亏{rp*100:.1f}%")[0])
res.append(run(A, gcap={"币": 3, "股票": 2, "金银": 2}, risk_pct=0.005, label="每组上限(3/2/2) + 每笔亏0.5%")[0])
res.append(run(A, gcap={"币": 3, "股票": 2, "金银": 2}, wstop=96, label="每组上限(3/2/2) + 周亏3%停")[0])
R = pd.DataFrame(res); R.to_csv("risk_report.csv", index=False)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
print(R.to_string(index=False))
# 同时亏：按周看各组盈亏的相关
W = A.assign(wk=A.exit_ts.dt.tz_localize(None).dt.to_period("W")).pivot_table(index="wk", columns="G", values="u", aggfunc="sum").fillna(0)
print("\n各组每周盈亏相关:\n", W.corr().round(2)); print("最差的5周:\n", W.assign(合计=W.sum(1)).sort_values("合计").head(5).round(0))
S = A[A.G == "币"]; Ws = S.assign(wk=S.exit_ts.dt.tz_localize(None).dt.to_period("W")).pivot_table(index="wk", columns="sym", values="u", aggfunc="sum").fillna(0)
print("7个币之间每周盈亏平均相关:", round(Ws.corr().where(~np.eye(7, dtype=bool)).stack().mean(), 2))
S = A[A.G == "股票"]; Ws = S.assign(wk=S.exit_ts.dt.tz_localize(None).dt.to_period("W")).pivot_table(index="wk", columns="sym", values="u", aggfunc="sum").fillna(0)
print("3只股票之间:", round(Ws.corr().where(~np.eye(len(Ws.columns), dtype=bool)).stack().mean(), 2))
yr = P0.groupby(P0.index.year).sum().round(0); print("按年(现在的做法):", yr.to_dict())
