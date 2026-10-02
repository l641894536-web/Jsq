import io
import zipfile

import pandas as pd

from jsq import vision
from jsq.data import load_frame

H = 3_600_000


def _zip(text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", text)
    return b.getvalue()


class Resp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content

    def raise_for_status(self):
        pass


class FakeVision:
    """2024-01、2024-02 两个月；klines 带表头，premium 不带表头（两种格式都存在）。"""
    def get(self, url, timeout=None):
        m = url.rsplit("-", 2)[-2:]
        month = f"{m[0]}-{m[1][:2]}"
        if month not in ("2024-01", "2024-02"):
            return Resp(404)
        t0 = int(pd.Timestamp(month + "-01", tz="UTC").timestamp() * 1000)
        n = 24 * 3
        if "fundingRate" in url:
            rows = ["calc_time,funding_interval_hours,last_funding_rate"]
            rows += [f"{t0 + 8 * H * (i + 1)},8,0.0001" for i in range(n // 8)]
        else:
            head = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
            rows = [head] if "/klines/" in url else []
            rows += [f"{t0 + H * i},1,2,0.5,1.5,10,{t0 + H * (i + 1) - 1},15,3,6,9,0" for i in range(n)]
        return Resp(200, _zip("\n".join(rows)))


def test_vision_download_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "_months", lambda start, end=None: ["2023-12", "2024-01", "2024-02"])
    n = vision.update_symbol_vision(FakeVision(), "TESTUSDT", "1h", "2023-12-01", tmp_path, workers=2)
    assert n == {"klines": 144, "premium": 144, "funding": 18}
    # 再跑一次：从最后一个月重新下载，不应产生重复
    n = vision.update_symbol_vision(FakeVision(), "TESTUSDT", "1h", "2023-12-01", tmp_path, workers=2)
    assert n["klines"] == 144
    df = load_frame("TESTUSDT", "1h", tmp_path)
    assert df["prem_close"].notna().all()
    assert (df["funding_paid"] != 0).sum() == 18
    assert df["funding_ann"].dropna().iloc[0] == 0.0001 * 3 * 365
