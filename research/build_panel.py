"""把 2014–2026 全A股日线整理成 日期×股票 的矩阵（npy），供后面算情绪指标和个股信号。"""
import glob, os
import numpy as np
import pandas as pd

SRC = "/home/claude/market-data/a_share/daily"
OUT = "/home/claude/bt/panel"
os.makedirs(OUT, exist_ok=True)
cols = ["date", "code", "high", "low", "close", "preclose", "amount", "tradestatus", "pctChg", "isST", "turn"]
parts = []
for f in sorted(glob.glob(f"{SRC}/*/*.csv.xz")):
    y = int(f.split("/")[-2])
    if y < 2014:
        continue
    d = pd.read_csv(f, usecols=cols, dtype={"date": str, "code": str})
    for c in ["high", "low", "close", "preclose", "amount", "pctChg", "turn"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
    d["tradestatus"] = pd.to_numeric(d["tradestatus"], errors="coerce").fillna(0).astype("int8")
    d["isST"] = pd.to_numeric(d["isST"], errors="coerce").fillna(0).astype("int8")
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
df = df[df.code.str.match(r"^(sh\.6|sz\.0|sz\.3)")]
print("rows", len(df), "dates", df.date.nunique(), "codes", df.code.nunique())
dates = np.sort(df.date.unique()); codes = np.sort(df.code.unique())
di = pd.Index(dates).get_indexer(df.date); ci = pd.Index(codes).get_indexer(df.code)
np.save(f"{OUT}/dates.npy", dates.astype("U10")); np.save(f"{OUT}/codes.npy", codes.astype("U9"))
for c, dt, fill in [("high", "float32", np.nan), ("low", "float32", np.nan), ("close", "float32", np.nan),
                    ("preclose", "float32", np.nan), ("amount", "float32", np.nan), ("pctChg", "float32", np.nan),
                    ("turn", "float32", np.nan), ("tradestatus", "int8", 0), ("isST", "int8", 0)]:
    m = np.full((len(dates), len(codes)), fill, dtype=dt)
    m[di, ci] = df[c].to_numpy()
    np.save(f"{OUT}/{c}.npy", m)
print("saved", (len(dates), len(codes)))
