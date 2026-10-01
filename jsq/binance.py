"""币安 U 本位合约公开行情接口（无需 API Key）。"""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from .config import INTERVAL_MS, TRADFI_KEYWORDS

log = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"
KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]
KLINE_LIMIT = 1500
FUNDING_LIMIT = 1000


class BinanceClient:
    def __init__(self, base_url: str = BASE_URL, proxy: str | None = None,
                 timeout: float = 20, pause: float = 0.15, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.timeout = timeout
        self.pause = pause

    def get(self, path: str, params: dict | None = None):
        last_err = None
        for attempt in range(6):
            try:
                r = self.session.get(self.base_url + path, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = e
                log.warning("网络错误 %s，%ds 后重试: %s", path, 2 ** attempt, e)
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 451:
                raise RuntimeError("币安拒绝了当前地区的 IP (HTTP 451)。请使用代理，例如 --proxy http://127.0.0.1:7890")
            if r.status_code in (418, 429):
                wait = int(r.headers.get("Retry-After", 5 * 2 ** attempt))
                log.warning("触发限频 (HTTP %s)，等待 %ds", r.status_code, wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                last_err = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"请求失败 {path} {params}: HTTP {r.status_code} {r.text[:200]}")
            if self.pause:
                time.sleep(self.pause)
            return r.json()
        raise RuntimeError(f"多次重试后仍失败 {path} {params}: {last_err}")

    # ---- 交易所信息 ----
    def exchange_info(self) -> dict:
        return self.get("/fapi/v1/exchangeInfo")

    def perpetual_symbols(self) -> pd.DataFrame:
        rows = []
        for s in self.exchange_info()["symbols"]:
            if s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT":
                continue
            rows.append({
                "symbol": s["symbol"],
                "base": s.get("baseAsset", ""),
                "status": s.get("status", ""),
                "underlying_type": s.get("underlyingType", ""),
                "underlying_sub_type": ",".join(s.get("underlyingSubType") or []),
                "onboard": pd.to_datetime(s.get("onboardDate", 0), unit="ms", utc=True),
            })
        return pd.DataFrame(rows)

    # ---- K 线 / 溢价指数 K 线 ----
    def klines(self, symbol: str, interval: str, start_ms: int, end_ms: int,
               premium: bool = False) -> pd.DataFrame:
        path = "/fapi/v1/premiumIndexKlines" if premium else "/fapi/v1/klines"
        step = INTERVAL_MS[interval]
        rows: list = []
        cur = start_ms
        while cur < end_ms:
            batch = self.get(path, {"symbol": symbol, "interval": interval, "startTime": cur,
                                    "endTime": end_ms, "limit": KLINE_LIMIT})
            if not batch:
                break
            rows.extend(batch)
            nxt = int(batch[-1][0]) + step
            if nxt <= cur:
                break
            cur = nxt
        if not rows:
            return pd.DataFrame(columns=KLINE_COLS[:-1])
        df = pd.DataFrame([r[:12] for r in rows], columns=KLINE_COLS).drop(columns="ignore")
        for c in df.columns:
            df[c] = pd.to_numeric(df[c])
        # 去掉尚未收盘的 K 线
        now_ms = int(time.time() * 1000)
        df = df[df["close_time"] < now_ms]
        return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)

    # ---- 资金费率历史 ----
    def funding_rates(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows: list = []
        cur = start_ms
        while cur < end_ms:
            batch = self.get("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": cur,
                                                      "endTime": end_ms, "limit": FUNDING_LIMIT})
            if not batch:
                break
            rows.extend(batch)
            cur = int(batch[-1]["fundingTime"]) + 1
            if len(batch) < FUNDING_LIMIT:
                break
        if not rows:
            return pd.DataFrame(columns=["funding_time", "funding_rate", "mark_price"])
        df = pd.DataFrame(rows)
        df = pd.DataFrame({
            "funding_time": pd.to_numeric(df["fundingTime"]),
            "funding_rate": pd.to_numeric(df["fundingRate"]),
            "mark_price": pd.to_numeric(df.get("markPrice", pd.Series([None] * len(df))), errors="coerce"),
        })
        return df.drop_duplicates("funding_time").sort_values("funding_time").reset_index(drop=True)


def classify_symbol(base: str, underlying_type: str) -> str:
    for cat, keys in TRADFI_KEYWORDS.items():
        if base.upper() in keys:
            return cat
    if underlying_type and underlying_type.upper() not in ("COIN", "INDEX", "PREMARKET", ""):
        return f"其他({underlying_type})"
    return ""
