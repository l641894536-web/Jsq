"""被套30%之后：什么状态下死扛/加仓是对的，什么状态下是坑（A股、美股，2021-11→，250天后）。
状态（起点当天能看到）：
  大盘：范围内等权指数在200日线上/下
  是不是它自己的问题：之前60天这只股票比大盘多跌了20%以上（个股出事）/ 跟着大盘跌
  跌的速度：从一年高点跌到-30%用了不到40个交易日（急跌）/ 更慢（阴跌）
  A股：赚不赚钱（市盈率TTM>0）；美股：营收和净利润同比都在前50%（成长）
结果：死扛250天后、越跌越加（跌10%/20%各加1份，按起点1份算的盈亏）、比大盘。
"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import holder_bt
from rally_dip_bt import panel_a, panel_us
import apanel

pct = lambda v: f"{v*100:+.1f}%"


def feats(R, dates, adjf, ew, extra=None):
    ewi = (1 + ew).cumprod().to_numpy(); ma = pd.Series(ewi).rolling(200, min_periods=150).mean().to_numpy()
    hi = pd.DataFrame(adjf).rolling(250, min_periods=200).max().to_numpy()
    out = []
    for _, r in R.iterrows():
        i, j = int(r.i), int(r.j); c = adjf[:, j]
        f = {"mkt_up": ewi[i] > ma[i]}
        f["rel60"] = (c[i] / c[i - 60] - 1) - (ewi[i] / ewi[i - 60] - 1)
        k = i - 1
        while k > i - 250 and c[k] < hi[i, j] * 0.999: k -= 1
        f["speed"] = i - k
        end = i + holder_bt.H; cE = c[end]; p0 = c[i]
        pnl = cE / p0 - 1
        for lvl in (0.9, 0.8):
            hit = np.where(c[i + 1:end + 1] <= p0 * lvl)[0]
            if len(hit): pnl += cE / c[i + 1 + hit[0]] - 1
        f["avg_pnl"] = pnl
        f["exc"] = r.hold - r.mkt
        if extra is not None: f.update(extra(i, j, r))
        out.append(f)
    return pd.concat([R.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def show(R, lab):
    print(f"\n######## {lab}  共 {len(R):,} 次；全部：死扛 {pct(R.hold.mean())}（最差10% {pct(R.hold.quantile(.1))}），比大盘 {pct(R.exc.mean())}；越跌越加盈亏 {pct(R.avg_pnl.mean())}（最差10% {pct(R.avg_pnl.quantile(.1))}）")
    splits = [("大盘在200日线上", R.mkt_up), ("大盘在200日线下", ~R.mkt_up),
              ("个股出事(比大盘多跌20%+)", R.rel60 <= -0.2), ("跟着大盘跌", R.rel60 > -0.2),
              ("急跌(<40天)", R.speed < 40), ("阴跌(≥40天)", R.speed >= 40)]
    if "good" in R:
        splits += [(R.attrs["good"], R.good == 1), (R.attrs["bad"], R.good == 0)]
    splits += [("大盘上+个股出事", R.mkt_up & (R.rel60 <= -0.2)), ("大盘上+跟着大盘跌", R.mkt_up & (R.rel60 > -0.2)),
               ("大盘下+个股出事", ~R.mkt_up & (R.rel60 <= -0.2)), ("大盘下+跟着大盘跌", ~R.mkt_up & (R.rel60 > -0.2))]
    if "good" in R:
        splits += [("大盘上+" + R.attrs["good"], R.mkt_up & (R.good == 1)), ("大盘下+" + R.attrs["bad"], ~R.mkt_up & (R.good == 0))]
    rows = []
    for nm, m in splits:
        x = R[m]
        if len(x) < 30: continue
        rows.append({"状态": nm, "次数": len(x), "死扛": pct(x.hold.mean()), "死扛中位": pct(x.hold.median()), "比大盘": pct(x.exc.mean()),
                     "死扛最差10%": pct(x.hold.quantile(.1)), "再跌20%+": f"{(x.mdd<=-0.2).mean():.0%}",
                     "反弹卖一半": pct(x.half.mean()), "反弹清仓不回": pct(x.out1.mean()), "清仓比死扛好的比例": f"{(x.out1>x.hold).mean():.0%}",
                     "加仓盈亏": pct(x.avg_pnl.mean()), "加仓最差10%": pct(x.avg_pnl.quantile(.1)),
                     "前半死扛": pct(x[x.per == '前半'].hold.mean()), "后半死扛": pct(x[x.per == '后半'].hold.mean())})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    da = panel_a(); RA = holder_bt.run(*da, "A股")
    P = apanel.build(extra=True); pe = P["peTTM"]
    def a_extra(i, j, r):
        v = pe[i, j]
        return {"good": int(np.isfinite(v) and v > 0) if np.isfinite(v) else np.nan}
    FA = feats(RA, *da[:2], da[3], a_extra)
    FA.attrs.update(good="赚钱(市盈率>0)", bad="亏钱(市盈率<0)")
    show(FA, "A股")

    du = panel_us(); RU = holder_bt.run(*du, "美股")
    from us_growth_lib import build_growth
    g = build_growth(); cols = None
    import rally_dip_bt
    from market_data import load
    uni = load.us_universe(); tk = [t for t in uni.ticker if "=" not in t and "^" not in t and "-" not in t]
    d = load.us_daily(tk, start="2019-06-01")
    C = d.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    bad = set("BITO DRAM EIDO EWJ EWT EWY EWZ EWZS GDX INTW IWM KORU KSTR LYTE MSTU MUU MVLL NVDL QQQ RAM SKDD SKUU SMH SNXX SOXL SOXS SQQQ TBT TMF TQQQ TSLL TZA URNM XBI XLE SPY".split())
    cols = [c for c in C.columns if c not in bad]
    dates = du[0]
    cache = {}
    def u_extra(i, j, r):
        dd = dates[i]
        if dd not in cache:
            snap = g[(g.filed < dd) & (g.end > dd - pd.Timedelta(days=200))].sort_values("end").groupby(["ticker", "kind"]).last()
            rv = snap.xs("rev", level="kind").yoy; ni = snap.xs("ni", level="kind").yoy
            cache[dd] = (rv, ni, rv.median(), ni.median())
        rv, ni, rm, nm = cache[dd]; t = cols[j]
        if t not in rv.index or t not in ni.index: return {"good": np.nan}
        return {"good": int(rv[t] >= rm and ni[t] >= nm)}
    FU = feats(RU, *du[:2], du[3], u_extra)
    FU.attrs.update(good="成长(营收利润同比都前50%)", bad="非成长")
    show(FU, "美股")
    pd.to_pickle({"A": FA, "US": FU}, "/home/claude/bt/_holder3.pkl")
