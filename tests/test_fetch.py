import pandas as pd

from jsq.binance import BinanceClient
from jsq.data import load_frame, update_symbol

H = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01


class FakeResp:
    def __init__(self, data):
        self.status_code = 200
        self._d = data
        self.headers = {}

    def json(self):
        return self._d


class FakeSession:
    """模拟币安分页接口：每次最多返回 limit 条。"""

    def __init__(self, n_bars=3500):
        self.n = n_bars
        self.proxies = {}
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if url.endswith("fundingRate"):
            ts = [T0 + 8 * H * i + 5 for i in range(self.n // 8)]
            ts = [t for t in ts if params["startTime"] <= t <= params["endTime"]][: params["limit"]]
            return FakeResp([{"fundingTime": t, "fundingRate": "0.0001", "markPrice": "1"} for t in ts])
        ts = [T0 + H * i for i in range(self.n)]
        ts = [t for t in ts if params["startTime"] <= t <= params["endTime"]][: params["limit"]]
        return FakeResp([[t, "1", "2", "0.5", "1.5", "10", t + H - 1, "15", 3, "6", "9", "0"] for t in ts])


def test_pagination_and_incremental_update(tmp_path):
    s = FakeSession(3500)
    c = BinanceClient(session=s, pause=0)
    update_symbol(c, "TESTUSDT", "1h", "2024-01-01", tmp_path)
    k = pd.read_csv(tmp_path / "TESTUSDT_1h_klines.csv")
    assert len(k) == 3500 and k["open_time"].is_monotonic_increasing
    f = pd.read_csv(tmp_path / "TESTUSDT_funding.csv")
    assert len(f) == 3500 // 8
    # 再次更新不应产生重复
    s.n = 3600
    update_symbol(c, "TESTUSDT", "1h", "2024-01-01", tmp_path)
    assert len(pd.read_csv(tmp_path / "TESTUSDT_1h_klines.csv")) == 3600
    df = load_frame("TESTUSDT", "1h", tmp_path)
    assert df["taker_buy_ratio"].iloc[0] == 0.6
    assert df["funding_ann"].dropna().iloc[0] == 0.0001 * 3 * 365
