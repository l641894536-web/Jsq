"""额外数据：持仓量 / 多空比 / 主动买卖比（metrics）与 订单簿深度（bookDepth）。

来源：data.binance.vision 的 U 本位合约日度文件，下载时直接聚合成 1 小时，只保存聚合结果：
  {SYM}_metrics_1h.csv  hour(ms), oi, oi_value, top_acct_ls, top_pos_ls, global_ls, taker_ls
  {SYM}_book_1h.csv     hour(ms), imb1, imb2, imb5, imb1_mean, depth1
所有值都取该小时内“最后一条”记录（imb1_mean/taker_ls 为小时内均值），在该小时 K 线收盘时可知。
"""
from __future__ import annotations

import io
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE = "https://data.binance.vision/data/futures/um/daily"
KINDS = {"metrics": "metrics_1h", "bookDepth": "book_1h"}


def path(data_dir: Path, symbol: str, kind: str) -> Path:
    return Path(data_dir) / f"{symbol}_{KINDS[kind]}.csv"


def _get(session, url) -> pd.DataFrame | None:
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60)
        except requests.RequestException:
            if attempt == 3:
                raise
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            continue
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open(z.namelist()[0]) as f:
                return pd.read_csv(f)
    return None


def _hour_ms(ts: pd.Series) -> np.ndarray:
    t = pd.to_datetime(ts, utc=True, errors="coerce").dt.floor("h")
    return (t.dt.tz_localize(None).values.astype("datetime64[ms]").astype("int64"))


def agg_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("create_time")
    h = _hour_ms(df["create_time"])
    out = pd.DataFrame({
        "hour": h,
        "oi": pd.to_numeric(df["sum_open_interest"], errors="coerce").values,
        "oi_value": pd.to_numeric(df["sum_open_interest_value"], errors="coerce").values,
        "top_acct_ls": pd.to_numeric(df["count_toptrader_long_short_ratio"], errors="coerce").values,
        "top_pos_ls": pd.to_numeric(df["sum_toptrader_long_short_ratio"], errors="coerce").values,
        "global_ls": pd.to_numeric(df["count_long_short_ratio"], errors="coerce").values,
        "taker_ls": pd.to_numeric(df["sum_taker_long_short_vol_ratio"], errors="coerce").values,
    })
    g = out.groupby("hour")
    last = g[["oi", "oi_value", "top_acct_ls", "top_pos_ls", "global_ls"]].last()
    # 主动买卖量比有极端值，取对数后平均
    last["taker_ls"] = np.log(g["taker_ls"].apply(lambda x: x[(x > 0) & np.isfinite(x)].mean() if len(x) else np.nan))
    return last.reset_index()


def agg_book(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["pct"] = pd.to_numeric(df["percentage"], errors="coerce")
    df["notional"] = pd.to_numeric(df["notional"], errors="coerce")
    w = df.pivot_table(index="ts", columns="pct", values="notional", aggfunc="last").sort_index()

    def imb(p):
        if -p not in w or p not in w:
            return pd.Series(np.nan, index=w.index)
        b, a = w[-p], w[p]
        return (b - a) / (b + a)

    snap = pd.DataFrame({"imb1": imb(1.0), "imb2": imb(2.0), "imb5": imb(5.0),
                         "depth1": (w.get(-1.0, np.nan) + w.get(1.0, np.nan))})
    snap["hour"] = _hour_ms(pd.Series(snap.index))
    g = snap.groupby("hour")
    out = g[["imb1", "imb2", "imb5", "depth1"]].last()
    out["imb1_mean"] = g["imb1"].mean()
    return out.reset_index()


def _days(start: str, end: pd.Timestamp | None = None) -> list[str]:
    end = end or pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(pd.Timestamp(start), end, freq="D")]


def update(session, symbol: str, kind: str, start: str, data_dir: Path, workers: int = 12,
           listed_from: str | None = None) -> int:
    p = path(data_dir, symbol, kind)
    days = _days(max(start, listed_from) if listed_from else start)
    if p.exists():
        old = pd.read_csv(p)
        if len(old):
            last_day = pd.Timestamp(int(old["hour"].max()), unit="ms").strftime("%Y-%m-%d")
            days = [d for d in days if d >= last_day]
    else:
        old = None
    agg = agg_metrics if kind == "metrics" else agg_book

    def one(day):
        raw = _get(session, f"{BASE}/{kind}/{symbol}/{symbol}-{kind}-{day}.zip")
        if raw is None or not len(raw):
            return None
        try:
            return agg(raw)
        except Exception as e:  # noqa: BLE001  个别日文件格式异常时跳过
            log.debug("%s %s %s 解析失败: %s", symbol, kind, day, e)
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = [x for x in ex.map(one, days) if x is not None]
    frames = ([old] if old is not None else []) + parts
    if not frames:
        return 0
    df = pd.concat(frames, ignore_index=True).drop_duplicates("hour", keep="last").sort_values("hour")
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return len(df)


def attach(df: pd.DataFrame, symbol: str, data_dir: Path) -> pd.DataFrame:
    """把小时级额外数据按“收盘可知”的原则对齐到 K 线表上。"""
    bar_end = df.index + pd.Timedelta(hours=df.attrs.get("bar_hours", 1.0))
    left = pd.DataFrame({"t": pd.DatetimeIndex(bar_end).as_unit("ns")})
    for kind in KINDS:
        p = path(data_dir, symbol, kind)
        if not p.exists():
            continue
        x = pd.read_csv(p)
        if not len(x):
            continue
        # 小时 h 的数据在 h+1h 时可知
        x["t"] = pd.DatetimeIndex(pd.to_datetime(x.pop("hour") + 3_600_000, unit="ms", utc=True)).as_unit("ns")
        x = x.sort_values("t")
        m = pd.merge_asof(left, x, on="t", direction="backward", tolerance=pd.Timedelta(hours=3))
        for c in x.columns:
            if c != "t":
                df[c] = m[c].values
    return df


LIVE_ENDPOINTS = {
    # 接口: [(返回字段, 本地列名)]，最多约 30 天、500 条
    "/futures/data/openInterestHist": [("sumOpenInterest", "oi"), ("sumOpenInterestValue", "oi_value")],
    "/futures/data/topLongShortAccountRatio": [("longShortRatio", "top_acct_ls")],
    "/futures/data/topLongShortPositionRatio": [("longShortRatio", "top_pos_ls")],
    "/futures/data/globalLongShortAccountRatio": [("longShortRatio", "global_ls")],
    "/futures/data/takerlongshortRatio": [("buySellRatio", "taker_ls")],
}


def update_live(client, symbol: str, data_dir: Path) -> int:
    """用币安实时接口补最近 ~20 天的持仓量/多空比（需要能访问 fapi.binance.com，国内一般要代理）。"""
    cols = {}
    for ep, fields in LIVE_ENDPOINTS.items():
        rows = client.get(ep, {"symbol": symbol, "period": "1h", "limit": 500}) or []
        for r in rows:
            h = int(r["timestamp"]) // 3_600_000 * 3_600_000
            for src, dst in fields:
                v = float(r[src])
                cols.setdefault(h, {})[dst] = np.log(v) if dst == "taker_ls" and v > 0 else v
    if not cols:
        return 0
    new = pd.DataFrame.from_dict(cols, orient="index").rename_axis("hour").reset_index()
    p = path(data_dir, symbol, "metrics")
    old = pd.read_csv(p) if p.exists() else pd.DataFrame()
    df = pd.concat([old, new], ignore_index=True).drop_duplicates("hour", keep="first").sort_values("hour")
    df.to_csv(p, index=False)
    return len(new)
