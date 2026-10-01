"""币安官方历史数据站 data.binance.vision（静态 zip 文件，无需 API，通常不受地区限制）。

U 本位合约按月提供：
  klines/{SYM}/{interval}/{SYM}-{interval}-{YYYY-MM}.zip
  premiumIndexKlines/{SYM}/{interval}/{SYM}-{interval}-{YYYY-MM}.zip
  fundingRate/{SYM}/{SYM}-fundingRate-{YYYY-MM}.zip
只下载已经结束的完整月份，三类数据的截止时间因此一致（资金费率没有日度文件）。
"""
from __future__ import annotations

import io
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from .binance import KLINE_COLS
from .config import TRADFI_KEYWORDS
from .data import _merge_save, paths

log = logging.getLogger(__name__)

BASE = "https://data.binance.vision/data/futures/um/monthly"


def make_session(proxy: str | None = None) -> requests.Session:
    s = requests.Session()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def _months(start: str, end: pd.Timestamp | None = None) -> list[str]:
    """start 所在月 到 上个完整月。"""
    end = end or pd.Timestamp.now(tz="UTC")
    last = (end.tz_localize(None) if end.tzinfo else end).to_period("M") - 1
    first = pd.Timestamp(start).to_period("M")
    return [str(p) for p in pd.period_range(first, last, freq="M")] if first <= last else []


def _url(kind: str, symbol: str, interval: str, month: str) -> str:
    if kind == "funding":
        return f"{BASE}/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
    folder = "klines" if kind == "klines" else "premiumIndexKlines"
    return f"{BASE}/{folder}/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"


def _fetch_csv(session: requests.Session, url: str) -> pd.DataFrame | None:
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60)
        except requests.RequestException as e:
            if attempt == 3:
                raise
            log.debug("重试 %s: %s", url, e)
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            continue
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open(z.namelist()[0]) as f:
                return pd.read_csv(f, header=None, dtype=str)
    raise RuntimeError(f"下载失败 {url}")


def _strip_header(raw: pd.DataFrame) -> pd.DataFrame:
    if len(raw) and not str(raw.iloc[0, 0]).strip().lstrip("-").isdigit():
        raw = raw.iloc[1:]
    return raw


def _to_ms(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s)
    return v.where(v < 1e14, v // 1000).astype("int64")   # 个别新文件用微秒


def _parse_klines(raw: pd.DataFrame, premium: bool) -> pd.DataFrame:
    raw = _strip_header(raw).iloc[:, :12]
    raw.columns = KLINE_COLS[: raw.shape[1]]
    df = raw.drop(columns=[c for c in ("ignore",) if c in raw]).apply(pd.to_numeric, errors="coerce")
    df["open_time"] = _to_ms(raw["open_time"])
    if "close_time" in df:
        df["close_time"] = _to_ms(raw["close_time"])
    if premium:
        df = df[["open_time", "open", "high", "low", "close"]]
    return df


def _parse_funding(raw: pd.DataFrame) -> pd.DataFrame:
    # 列: calc_time, funding_interval_hours, last_funding_rate
    raw = _strip_header(raw)
    return pd.DataFrame({
        "funding_time": _to_ms(raw.iloc[:, 0]).values,
        "funding_rate": pd.to_numeric(raw.iloc[:, -1], errors="coerce").values,
        "mark_price": float("nan"),
    })


def _last_month(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    try:
        last = pd.read_csv(path, usecols=[key])[key].max()
    except (ValueError, pd.errors.EmptyDataError):
        return None
    if pd.isna(last):
        return None
    return str(pd.Timestamp(int(last), unit="ms").to_period("M"))


def update_symbol_vision(session: requests.Session, symbol: str, interval: str, start: str,
                         data_dir: Path, workers: int = 8) -> dict[str, int]:
    """下载/增量更新一个标的。已有数据从最后一个月重新下载（覆盖可能不完整的月）。"""
    p = paths(data_dir, symbol, interval)
    out = {}
    for kind, key in (("klines", "open_time"), ("premium", "open_time"), ("funding", "funding_time")):
        months = _months(start)
        last = _last_month(p[kind], key)
        if last:
            months = [m for m in months if m >= last]
        urls = [_url(kind, symbol, interval, m) for m in months]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            raws = list(ex.map(lambda u: _fetch_csv(session, u), urls))
        frames = []
        for raw in raws:
            if raw is None or not len(raw):
                continue
            frames.append(_parse_funding(raw) if kind == "funding" else _parse_klines(raw, kind == "premium"))
        new = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if len(new) or p[kind].exists():
            out[kind] = len(_merge_save(p[kind], new, key))
        else:
            out[kind] = 0
    return out


def probe_symbols(session: requests.Session, candidates: list[str] | None = None,
                  interval: str = "1h") -> pd.DataFrame:
    """检查哪些候选合约在历史数据站上有最近一个完整月的数据。"""
    # 上个月的月度文件通常要月初几天后才发布，找最近一个 BTCUSDT 已有文件的月份
    month = next((m for m in reversed(_months("2000-01")[-4:])
                  if session.head(_url("klines", "BTCUSDT", interval, m), timeout=20).status_code == 200), None)
    if month is None:
        raise RuntimeError("历史数据站最近几个月都没有 BTCUSDT 文件，请检查网络")
    if candidates is None:
        candidates = ["BTCUSDT", "ETHUSDT"] + sorted(
            {f"{b}USDT" for keys in TRADFI_KEYWORDS.values() for b in keys})

    def check(sym):
        try:
            r = session.head(_url("klines", sym, interval, month), timeout=20)
            return r.status_code == 200
        except requests.RequestException:
            return False

    with ThreadPoolExecutor(max_workers=8) as ex:
        ok = list(ex.map(check, candidates))
    cat = {f"{b}USDT": c for c, keys in TRADFI_KEYWORDS.items() for b in keys}
    return pd.DataFrame({"symbol": candidates, "category": [cat.get(s, "加密") for s in candidates],
                         "available": ok, "month": month})
