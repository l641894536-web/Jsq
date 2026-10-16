"""港股合约的真实交易成本：逐笔成交（aggTrades）估算有效价差，订单簿深度（bookDepth）估算 ±1% 内可成交金额。

有效价差：把成交按 5 秒分桶，桶内 主动买成交均价 - 主动卖成交均价 ≈ 买卖价差（含短期冲击），除以中间价。
只保留每天几个关键时段的统计，不保存原始逐笔数据。
"""
from __future__ import annotations

import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DAILY = "https://data.binance.vision/data/futures/um/daily"
# 香港时间 (开始, 结束)
WINDOWS = {"auction": ("09:20", "09:30"), "open": ("09:31", "09:41"), "am_close": ("11:50", "12:00"),
           "pm_open": ("13:01", "13:11"), "close": ("15:50", "16:00")}


def _days(session, kind, sym):
    r = session.get(S3, params={"prefix": f"data/futures/um/daily/{kind}/{sym}/"}, timeout=60)
    return sorted(set(re.findall(rf"{sym}-{kind}-(\d{{4}}-\d{{2}}-\d{{2}})\.zip<", r.text)))


def _csv(session, url):
    for _ in range(3):
        try:
            r = session.get(url, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            return pd.read_csv(z.open(z.namelist()[0]))
        except (requests.RequestException, zipfile.BadZipFile, pd.errors.ParserError):
            continue
    return None


def _hkt(ms) -> pd.DatetimeIndex:
    ms = np.asarray(pd.to_numeric(pd.Series(ms)), dtype="int64")
    ms = np.where(ms < 1e14, ms, ms // 1000)
    return pd.DatetimeIndex(pd.to_datetime(ms, unit="ms", utc=True)).tz_convert("Asia/Hong_Kong")


def _in_window(t: pd.DatetimeIndex, a: str, b: str) -> np.ndarray:
    hm = t.strftime("%H:%M")
    return np.asarray((hm >= a) & (hm < b))


def trades_day(df: pd.DataFrame) -> list[dict]:
    if "transact_time" not in df:  # 无表头的老格式
        df.columns = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time",
                      "is_buyer_maker"][: df.shape[1]]
    ms = pd.to_numeric(df["transact_time"])
    ms = ms.where(ms < 1e14, ms // 1000).to_numpy()
    t = _hkt(ms)
    px = pd.to_numeric(df["price"]).to_numpy()
    qty = pd.to_numeric(df["quantity"]).to_numpy()
    sell = df["is_buyer_maker"].astype(str).str.lower().eq("true").to_numpy()   # 买方是挂单方 = 主动卖
    out = []
    for w, (a, b) in WINDOWS.items():
        m = _in_window(t, a, b)
        if m.sum() < 5:
            out.append({"window": w, "trades": int(m.sum())})
            continue
        bucket = ms[m] // 5000
        d = pd.DataFrame({"b": bucket, "px": px[m], "q": qty[m], "sell": sell[m]})
        d["n"] = d["px"] * d["q"]
        g = d.groupby(["b", "sell"]).agg(n=("n", "sum"), q=("q", "sum")).reset_index()
        g["vwap"] = g["n"] / g["q"]
        p = g.pivot(index="b", columns="sell", values="vwap")
        if {False, True} <= set(p.columns):
            p = p.dropna()
            spread = ((p[False] - p[True]) / ((p[False] + p[True]) / 2)).clip(lower=-0.02, upper=0.05)
        else:   # 窗口内只有单边主动成交，无法估计价差
            spread = pd.Series(dtype=float)
        notional = d["n"].to_numpy()
        out.append({"window": w, "trades": int(m.sum()), "notional": float(notional.sum()),
                    "median_trade": float(np.median(notional)), "p90_trade": float(np.percentile(notional, 90)),
                    "spread_bps": float(spread.median() * 1e4) if len(spread) >= 3 else np.nan,
                    "spread_obs": int(len(spread))})
    return out


def depth_day(df: pd.DataFrame) -> list[dict]:
    t = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M:%S", utc=True,
                                        errors="coerce")).tz_convert("Asia/Hong_Kong")
    pct = pd.to_numeric(df["percentage"]).to_numpy()
    notional = pd.to_numeric(df["notional"]).to_numpy()
    out = []
    for w, (a, b) in WINDOWS.items():
        m = _in_window(t, a, b)
        bid = notional[m & (pct == -1)]
        ask = notional[m & (pct == 1)]
        bid02 = notional[m & np.isclose(pct, -0.2)]
        ask02 = notional[m & np.isclose(pct, 0.2)]
        med = lambda x: float(np.median(x)) if len(x) else np.nan  # noqa: E731
        out.append({"window": w, "depth1_bid": med(bid), "depth1_ask": med(ask),
                    "depth02_bid": med(bid02), "depth02_ask": med(ask02)})
    return out


def collect(session, sym: str, out_dir: Path, workers: int = 8) -> pd.DataFrame:
    p = Path(out_dir) / f"{sym}_micro.csv"
    old = pd.read_csv(p) if p.exists() else pd.DataFrame()
    done = set(old["day"]) if len(old) else set()
    days = [d for d in _days(session, "aggTrades", sym) if d not in done]

    def one(day):
        try:
            return _one(day)
        except Exception:  # noqa: BLE001  个别日文件异常时跳过，不影响其它日期
            return []

    def _one(day):
        rows = []
        tr = _csv(session, f"{DAILY}/aggTrades/{sym}/{sym}-aggTrades-{day}.zip")
        bd = _csv(session, f"{DAILY}/bookDepth/{sym}/{sym}-bookDepth-{day}.zip")
        tw = trades_day(tr) if tr is not None and len(tr) else []
        dw = {r["window"]: r for r in depth_day(bd)} if bd is not None and len(bd) else {}
        for r in tw:
            rows.append({"symbol": sym, "day": day, **r, **{k: v for k, v in dw.get(r["window"], {}).items() if k != "window"}})
        return rows

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = [r for rs in ex.map(one, days) for r in rs]
    df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if rows else old
    if len(df):
        df.to_csv(p, index=False)
    return df
