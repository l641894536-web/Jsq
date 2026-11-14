import os, sys, numpy as np, pandas as pd
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data"); sys.path.insert(0, "/home/claude/jsq")
from market_data import load
from rally_dip_bt import panel_us
D = pd.read_pickle("/home/claude/bt/_holder3.pkl"); FA, FU = D["A"], D["US"]
dates, adjf, U, ew = panel_us()
q = load.us_daily(["QQQ"], start="2019-01-01").set_index("date").adj_close.reindex(dates).ffill()
ma = q.rolling(200).mean().to_numpy(); qa = q.to_numpy()
FU["mkt_up"] = [qa[i] > ma[i] for i in FU.i]
FU["rel60"] = [(adjf[i, j] / adjf[i - 60, j] - 1) - (qa[i] / qa[i - 60] - 1) for i, j in zip(FU.i, FU.j)]
pct = lambda v: f"{v*100:+.1f}%"
for lab, F in [("A股", FA), ("美股", FU)]:
    print("####", lab)
    for nm, m in [("大盘下+跟着跌", ~F.mkt_up & (F.rel60 > -0.2)), ("大盘下(全部)", ~F.mkt_up), ("大盘上(全部)", F.mkt_up), ("大盘上+个股出事", F.mkt_up & (F.rel60 <= -0.2))]:
        for per in ["前半", "后半"]:
            x = F[m & (F.per == per)]
            print(f"  {nm:10s} {per} n={len(x):5d} 死扛{pct(x.hold.mean())} 中位{pct(x.hold.median())} 最差10%{pct(x.hold.quantile(.1))} | 加仓{pct(x.avg_pnl.mean())} 最差10%{pct(x.avg_pnl.quantile(.1))} | 卖一半{pct(x.half.mean())} 清仓不回{pct(x.out1.mean())} 清仓更好{(x.out1>x.hold).mean():.0%}")
    # 加仓平均用了几份
    print("  平均加到几份:", F.groupby(F.mkt_up).units.mean().round(2).to_dict())
