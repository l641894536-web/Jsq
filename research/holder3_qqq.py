"""美股：把'大盘'换成页面用的纳指100（QQQ）200日线、个股比QQQ多跌20%，结果是否一样。"""
import os, sys, numpy as np, pandas as pd
os.environ.setdefault("MARKET_DATA", "/home/claude/market-data")
sys.path.insert(0, "/home/claude/bt"); sys.path.insert(0, "/home/claude/jsq")
from market_data import load
from rally_dip_bt import panel_us
from holder3_bt import show
F = pd.read_pickle("/home/claude/bt/_holder3.pkl")["US"]
dates, adjf, U, ew = panel_us()
q = load.us_daily(["QQQ"], start="2019-01-01").set_index("date").adj_close.reindex(dates).ffill()
ma = q.rolling(200).mean().to_numpy(); qa = q.to_numpy()
F["mkt_up"] = [qa[i] > ma[i] for i in F.i]
F["rel60"] = [(adjf[i, j] / adjf[i - 60, j] - 1) - (qa[i] / qa[i - 60] - 1) for i, j in zip(F.i, F.j)]
F.attrs.update(good="成长(营收利润同比都前50%)", bad="非成长")
show(F, "美股（大盘=纳指100）")
