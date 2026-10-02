import numpy as np
import pandas as pd

from jsq import news
from jsq.data import load_frame
from jsq.newslab import events, run
from jsq.strategies import STRATEGIES
from jsq.synthetic import make_dataset


class Resp:
    def __init__(self, js):
        self.status_code, self._js, self.text = 200, js, "{}"

    def json(self):
        return self._js


class FakeGdelt:
    """按查询区间返回 15 分钟粒度的报道量/情绪，第 100 小时制造一次报道突增。"""
    t0 = pd.Timestamp("2024-01-01", tz="UTC")

    def get(self, url, params=None, timeout=None):
        s = pd.Timestamp(params["startdatetime"], tz="UTC")
        e = pd.Timestamp(params["enddatetime"], tz="UTC")
        ts = pd.date_range(s, e, freq="15min", inclusive="left")
        hours = ((ts - self.t0) / pd.Timedelta(hours=1)).astype(int)
        if params["mode"] == "timelinevolraw":
            data = [{"date": t.strftime("%Y%m%dT%H%M%SZ"), "value": 50 if h == 100 else 5, "norm": 10000}
                    for t, h in zip(ts, hours)]
        else:
            data = [{"date": t.strftime("%Y%m%dT%H%M%SZ"), "value": -5.0 if h == 100 else -1.0}
                    for t, h in zip(ts, hours)]
        return Resp({"timeline": [{"data": data}]})


def test_fetch_hourly_and_lagged_attach(tmp_path):
    df = news.fetch_topic(FakeGdelt(), "oil", FakeGdelt.t0, FakeGdelt.t0 + pd.Timedelta(days=10), pause=0)
    assert len(df) == 10 * 96 and {"count", "norm", "tone"} <= set(df.columns)
    df.to_csv(news.path(tmp_path, "oil"), index=False)
    h = news.hourly(tmp_path, "oil")
    assert np.isclose(h["vol"].iloc[100], 50 * 4 / 40000 * 1e6)
    syms = make_dataset(tmp_path, "1h", days=10)
    f = load_frame(syms[0], "1h", tmp_path, enrich=False)
    f = news.attach(f, tmp_path, ["oil"])
    # 第 100 小时的新闻：小时结束(101) + 1 小时延迟 = 102 点才可用 -> 收盘在 102 点的 K 线是第 101 根
    v = f["news_oil_vol"].to_numpy()
    assert v[101] > v[100] and np.isclose(v[101], h["vol"].iloc[100])


def test_event_study_and_news_strategies(tmp_path):
    syms = make_dataset(tmp_path, "1h", days=60)
    f = load_frame(syms[0], "1h", tmp_path, enrich=False)
    rng = np.random.default_rng(0)
    vol = np.where(np.arange(len(f)) % 2 == 0, 9.0, 11.0)  # 平稳的报道量，只有下面 3 次突增
    vol[[300, 500, 700, 900, 1100, 1300]] = 40
    f["news_oil_vol"] = vol
    f["news_oil_tone"] = rng.normal(-1, 0.3, len(f))
    ev = events(f, "oil")
    assert len(ev) == 6 and {"pre", "tone_dev", "fwd_24"} <= set(ev.columns)
    _, summ = run([f], cost=0.0007)
    assert {"follow_bps", "tone_bps", "vol_ratio"} <= set(summ.columns)
    for name in ("news_follow", "news_tone"):
        s = STRATEGIES[name].signal(f, {"topic": "oil", "z": 3.0, "side": 1})
        assert set(np.unique(s)) <= {-1, 0, 1} and (s != 0).any()
        cut = 900
        np.testing.assert_array_equal(s[:cut], STRATEGIES[name].signal(f.iloc[:cut], {"topic": "oil", "z": 3.0, "side": 1}))
