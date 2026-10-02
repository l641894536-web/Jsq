"""本地数据缓存（CSV）与特征表构建。

每个标的三份文件：
  {SYMBOL}_{interval}_klines.csv    K 线（含主动买入量）
  {SYMBOL}_{interval}_premium.csv   溢价指数 K 线（合约相对现货指数的溢价，资金费率的来源）
  {SYMBOL}_funding.csv              资金费率结算历史
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .config import INTERVAL_MS, bar_hours

log = logging.getLogger(__name__)


def paths(data_dir: Path, symbol: str, interval: str) -> dict[str, Path]:
    d = Path(data_dir)
    return {
        "klines": d / f"{symbol}_{interval}_klines.csv",
        "premium": d / f"{symbol}_{interval}_premium.csv",
        "funding": d / f"{symbol}_funding.csv",
    }


def _to_ms(ts: str | pd.Timestamp) -> int:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return int(t.timestamp() * 1000)


def _ns(t) -> np.ndarray:
    """UTC 时间序列 -> int64 纳秒（不依赖 pandas 的内部时间精度）。"""
    idx = pd.DatetimeIndex(t)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.values.astype("datetime64[ns]").astype("int64")


def _utc_ms(ms) -> pd.DatetimeIndex:
    """毫秒时间戳 -> 纳秒精度 UTC 时间（统一精度，避免 pandas 不同版本推断出 ms/us 精度导致对齐失败）。"""
    return pd.DatetimeIndex(pd.to_datetime(ms, unit="ms", utc=True)).as_unit("ns")


def _merge_save(path: Path, new: pd.DataFrame, key: str) -> pd.DataFrame:
    if path.exists():
        old = pd.read_csv(path)
        new = pd.concat([old, new], ignore_index=True) if len(new) else old
    new = new.drop_duplicates(key, keep="last").sort_values(key).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False)
    return new


def _resume_from(path: Path, key: str, start_ms: int, step_ms: int) -> int:
    if not path.exists():
        return start_ms
    try:
        last = pd.read_csv(path, usecols=[key])[key].max()
    except (ValueError, pd.errors.EmptyDataError):
        return start_ms
    if pd.isna(last):
        return start_ms
    return max(start_ms, int(last) + step_ms)


def update_symbol(client, symbol: str, interval: str, start: str, data_dir: Path) -> dict[str, int]:
    """增量下载到最新。返回各数据集的行数。"""
    p = paths(data_dir, symbol, interval)
    step = INTERVAL_MS[interval]
    start_ms = _to_ms(start)
    end_ms = _to_ms(pd.Timestamp.now(tz="UTC"))
    out = {}
    for kind, premium in (("klines", False), ("premium", True)):
        s = _resume_from(p[kind], "open_time", start_ms, step)
        new = client.klines(symbol, interval, s, end_ms, premium=premium) if s < end_ms else pd.DataFrame()
        if kind == "premium" and len(new):
            new = new[["open_time", "open", "high", "low", "close"]]
        out[kind] = len(_merge_save(p[kind], new, "open_time")) if (len(new) or p[kind].exists()) else 0
    s = _resume_from(p["funding"], "funding_time", start_ms, 1)
    new = client.funding_rates(symbol, s, end_ms) if s < end_ms else pd.DataFrame()
    out["funding"] = len(_merge_save(p["funding"], new, "funding_time")) if (len(new) or p["funding"].exists()) else 0
    return out


def load_frame(symbol: str, interval: str, data_dir: Path,
               start: str | None = None, end: str | None = None, enrich: bool = True) -> pd.DataFrame:
    """把 K 线、溢价、资金费率对齐成一张以 K 线开盘时间为索引的表。

    关键的防未来函数处理：
      funding_rate        —— 截至该 K 线收盘时“已结算”的最近一次资金费率（收盘时可知）
      funding_paid        —— 在 (开盘, 收盘] 内结算的费率之和，用于回测中扣/收资金费
      funding_ann         —— 年化资金费率，消除不同标的结算间隔(1h/4h/8h)的差异
    """
    p = paths(data_dir, symbol, interval)
    if not p["klines"].exists():
        raise FileNotFoundError(f"没有 {symbol} 的数据，请先运行 fetch: {p['klines']}")
    k = pd.read_csv(p["klines"])
    idx = _utc_ms(k["open_time"])
    cols = ["open", "high", "low", "close", "volume", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote"]
    df = pd.DataFrame({c: pd.to_numeric(k[c], errors="coerce").values for c in cols if c in k}, index=idx)
    df.index.name = "time"
    df = df[~df.index.duplicated(keep="last")].sort_index()

    bar = pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    bar_end = df.index + bar

    if p["premium"].exists():
        pr = pd.read_csv(p["premium"])
        pr.index = _utc_ms(pr["open_time"])
        pr = pr[~pr.index.duplicated(keep="last")]
        df["prem_close"] = pd.to_numeric(pr["close"], errors="coerce").reindex(df.index)
    else:
        df["prem_close"] = np.nan

    df["funding_rate"] = np.nan
    df["funding_ann"] = np.nan
    df["funding_paid"] = 0.0
    if p["funding"].exists():
        f = pd.read_csv(p["funding"])
        if len(f):
            # 结算时间常带几毫秒偏差，取整到分钟
            ft = pd.Series(_utc_ms(f["funding_time"]).round("min"))
            f = pd.DataFrame({"t": ft, "rate": pd.to_numeric(f["funding_rate"], errors="coerce")})
            f = f.dropna().drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)
            # 结算间隔（小时）：用相邻结算时间差，限制在 [1, 8]
            iv = f["t"].diff().dt.total_seconds().div(3600).clip(1, 8)
            f["interval_h"] = iv.bfill().fillna(8.0)
            # 超过 2 个结算周期没有新费率（例如历史数据站当月费率尚未发布）就视为缺失，不沿用旧值
            known = pd.merge_asof(pd.DataFrame({"t": pd.DatetimeIndex(bar_end).as_unit("ns")}), f, on="t",
                                  direction="backward", tolerance=pd.Timedelta(hours=17))
            df["funding_rate"] = known["rate"].values
            df["funding_ann"] = (known["rate"] * 24 * 365 / known["interval_h"]).values
            # 把每次结算分配给 (open, open+bar] 包含它的那根 K 线
            end_ns = _ns(bar_end)
            t_ns = _ns(f["t"])
            pos = np.searchsorted(end_ns, t_ns, side="left")
            ok = (pos < len(df)) & (pos >= 0)
            ok[ok] &= _ns(df.index)[pos[ok]] < t_ns[ok]
            paid = np.zeros(len(df))
            np.add.at(paid, pos[ok], f["rate"].values[ok])
            df["funding_paid"] = paid

    tb = df.get("taker_buy_base")
    df["taker_buy_ratio"] = (tb / df["volume"].replace(0, np.nan)) if tb is not None else np.nan

    df.attrs.update(symbol=symbol, interval=interval, bar_hours=bar_hours(interval))
    if enrich:
        from . import cross, extra
        df = extra.attach(df, symbol, data_dir)
        for c in ("oi", "oi_value"):
            if c in df:
                df[c] = df[c].where(df[c] > 0)
        df = cross.attach_peer(df, Path(data_dir), interval)
        from . import news
        df = news.attach(df, Path(data_dir))

    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index < pd.Timestamp(end, tz="UTC")]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df.attrs.update(symbol=symbol, interval=interval, bar_hours=bar_hours(interval))
    return df


def coverage(df: pd.DataFrame) -> dict:
    fr = df["funding_rate"].dropna()
    settle = df["funding_paid"].ne(0).sum()
    years = max((df.index[-1] - df.index[0]).total_seconds() / (365 * 86400), 1e-9)
    return {
        "symbol": df.attrs.get("symbol"),
        "start": df.index[0].strftime("%Y-%m-%d"),
        "end": df.index[-1].strftime("%Y-%m-%d"),
        "bars": len(df),
        "years": round(years, 2),
        "funding_settlements": int(settle),
        "funding_ann_mean": float(df["funding_ann"].mean()) if len(fr) else np.nan,
        "has_premium": bool(df["prem_close"].notna().any()),
        "buy_hold_return": float(df["close"].iloc[-1] / df["open"].iloc[0] - 1),
    }
