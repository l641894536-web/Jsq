"""新闻变量：GDELT 全球新闻库（每 15 分钟更新，免费，无需 Key）。

对每个主题取两条时间序列：
  * 报道量  —— 匹配文章数 / 全部文章数（去掉整体新闻量的日内、周末波动）
  * 情绪    —— 匹配文章的平均语气分（负 = 偏负面）
DOC 2.0 接口只覆盖最近约 3 个月，7 天以内的查询给 15 分钟精度，所以按周分段拉取后聚合成 1 小时。
数据保存在 data/news_{topic}.csv；对齐到 K 线时再额外延后 1 小时，模拟抓取/发布的延迟，避免用到未来信息。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

API = "https://api.gdeltproject.org/api/v2/doc/doc"

TOPICS = {
    "oil": '(crude OR OPEC OR "oil price" OR "oil prices" OR brent OR "oil supply" OR "oil output")',
    "trump_energy": 'trump (crude OR OPEC OR "oil price" OR iran OR sanctions OR drilling OR "strategic petroleum")',
    "opec": "(OPEC OR \"OPEC+\")",
    "mideast": '(iran OR "strait of hormuz" OR houthi OR "red sea" OR israel)',
    "russia_oil": 'russia (oil OR crude OR sanctions OR pipeline)',
}
TOPIC_CN = {"oil": "原油综合", "trump_energy": "特朗普+能源/伊朗/制裁", "opec": "OPEC",
            "mideast": "中东局势", "russia_oil": "俄罗斯石油/制裁"}


def path(data_dir: Path, topic: str) -> Path:
    return Path(data_dir) / f"news_{topic}.csv"


def _fmt(t: pd.Timestamp) -> str:
    return t.strftime("%Y%m%d%H%M%S")


def _get(session, params: dict, pause: float) -> dict | None:
    for attempt in range(5):
        try:
            r = session.get(API, params=params, timeout=60)
        except requests.RequestException as e:
            log.debug("GDELT 网络错误: %s", e)
            time.sleep(5 * (attempt + 1))
            continue
        time.sleep(pause)
        if r.status_code == 429 or "Please limit requests" in r.text[:200]:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code != 200:
            log.warning("GDELT HTTP %s: %s", r.status_code, r.text[:200])
            return None
        try:
            return r.json()
        except ValueError:
            log.warning("GDELT 返回非 JSON: %s", r.text[:200])
            return None
    return None


def _parse(js: dict | None, mode: str) -> pd.DataFrame:
    if not js or not js.get("timeline"):
        return pd.DataFrame()
    data = js["timeline"][0].get("data", [])
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["date"], format="%Y%m%dT%H%M%SZ", utc=True)
    if mode == "timelinevolraw":
        return pd.DataFrame({"time": df["time"], "count": pd.to_numeric(df["value"]),
                             "norm": pd.to_numeric(df.get("norm", np.nan))})
    return pd.DataFrame({"time": df["time"], "tone": pd.to_numeric(df["value"])})


def fetch_topic(session, topic: str, start: pd.Timestamp, end: pd.Timestamp, pause: float = 5.0) -> pd.DataFrame:
    q = TOPICS[topic]
    parts = []
    t = start
    while t < end:
        t2 = min(t + pd.Timedelta(days=7), end)
        frames = []
        for mode in ("timelinevolraw", "timelinetone"):
            js = _get(session, {"query": q, "mode": mode, "format": "json",
                                "startdatetime": _fmt(t), "enddatetime": _fmt(t2)}, pause)
            frames.append(_parse(js, mode))
        if len(frames[0]):
            x = frames[0]
            if len(frames[1]):
                x = x.merge(frames[1], on="time", how="left")
            parts.append(x)
        t = t2
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def update(session, topic: str, data_dir: Path, days: int = 90, pause: float = 5.0) -> int:
    p = path(data_dir, topic)
    end = pd.Timestamp.now(tz="UTC").floor("h")
    start = end - pd.Timedelta(days=days)
    old = pd.read_csv(p, parse_dates=["time"]) if p.exists() else pd.DataFrame()
    if len(old):
        start = max(start, old["time"].max() - pd.Timedelta(hours=6))
    new = fetch_topic(session, topic, start, end, pause)
    df = pd.concat([old, new], ignore_index=True) if len(old) else new
    if not len(df):
        return 0
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.drop_duplicates("time", keep="last").sort_values("time")
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return len(df)


def hourly(data_dir: Path, topic: str) -> pd.DataFrame | None:
    p = path(data_dir, topic)
    if not p.exists():
        return None
    x = pd.read_csv(p, parse_dates=["time"])
    if not len(x):
        return None
    x["time"] = pd.to_datetime(x["time"], utc=True)
    x["hour"] = x["time"].dt.floor("h")
    if "tone" not in x:
        x["tone"] = np.nan
    x["tone_w"] = x["tone"] * x["count"]
    g = x.groupby("hour").agg(count=("count", "sum"), norm=("norm", "sum"), tone_w=("tone_w", "sum"))
    out = pd.DataFrame(index=g.index)
    out["vol"] = g["count"] / g["norm"].replace(0, np.nan) * 1e6   # 每百万篇报道中的匹配篇数
    out["tone"] = g["tone_w"] / g["count"].replace(0, np.nan)
    return out


def attach(df: pd.DataFrame, data_dir: Path, topics=None, lag_hours: float = 1.0) -> pd.DataFrame:
    """新闻按小时对齐：第 h 小时的新闻在 h+1h（小时结束）+ lag_hours 之后才可用。"""
    bar_end = df.index + pd.Timedelta(hours=df.attrs.get("bar_hours", 1.0))
    left = pd.DataFrame({"t": pd.DatetimeIndex(bar_end).as_unit("ns")})
    for topic in topics or TOPICS:
        h = hourly(data_dir, topic)
        if h is None:
            continue
        h = h.reset_index()
        h["t"] = pd.DatetimeIndex(h.pop("hour") + pd.Timedelta(hours=1 + lag_hours)).as_unit("ns")
        m = pd.merge_asof(left, h.sort_values("t"), on="t", direction="backward", tolerance=pd.Timedelta(hours=2))
        df[f"news_{topic}_vol"] = m["vol"].values
        df[f"news_{topic}_tone"] = m["tone"].values
    return df
