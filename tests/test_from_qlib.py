"""qlib → 标准数据目录 的转换（用一个微型的假 qlib 目录，不联网）。"""

import numpy as np
import pandas as pd

from ashare_lab.core import stats
from ashare_lab.data import from_qlib as Q
from ashare_lab.data.industry_static import EM_TO_SW1, SW2014_TO_SW1, parse_hybk
from ashare_lab.data.market import SW1_NAMES


def _write_bin(path, start, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.r_[np.float32(start), np.asarray(values, dtype=np.float32)].astype("<f4").tofile(path)


def _fake_qlib(root):
    cal = pd.bdate_range("2020-01-01", periods=400)
    (root / "calendars").mkdir(parents=True)
    (root / "calendars" / "day.txt").write_text("\n".join(d.strftime("%Y-%m-%d") for d in cal))
    inst = root / "instruments"
    inst.mkdir()
    syms = ["SH600000", "SZ000001", "SZ300750", "SZ399300", "SH000300"]
    (inst / "all.txt").write_text("".join(f"{s}\t2020-01-01\t2021-12-31\n" for s in syms))
    (inst / "csi300.txt").write_text("SH600000\t2020-01-01\t2021-12-31\n")
    (inst / "csi500.txt").write_text("SZ000001\t2020-06-01\t2021-12-31\n")
    (inst / "csi1000.txt").write_text("")
    rng = np.random.default_rng(0)
    n = len(cal)
    for s in syms:
        close = 10 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))
        amount = np.full(n, 1e5)  # 千元
        if s == "SZ399300":
            amount = np.full(n, 1e9)  # 指数的巨额成交额，不能混进个股
        vwap = close.copy()
        if s == "SZ300750":
            amount[100] = 1e8        # 单位错误：成交额放大 1000 倍
            vwap[100] = close[100] * 1000
        d = root / "features" / s.lower()
        for name, v in (("close", close), ("amount", amount), ("vwap", vwap), ("high", close * 1.02), ("low", close * 0.98)):
            _write_bin(d / f"{name}.day.bin", 0, v)
    return cal


def test_read_bin_offset(tmp_path):
    p = tmp_path / "x.day.bin"
    _write_bin(p, 3, [1.0, 2.0])
    out = Q.read_bin(p, 6)
    assert np.isnan(out[:3]).all() and out[3] == 1.0 and out[4] == 2.0 and np.isnan(out[5])


def test_stock_regex_excludes_szse_indices():
    assert Q.STOCK_RE.match("SZ000001") and Q.STOCK_RE.match("SZ300750") and Q.STOCK_RE.match("SH688981")
    assert not Q.STOCK_RE.match("SZ399300") and not Q.STOCK_RE.match("SH000300")


def test_build_standard_dir(tmp_path):
    q = tmp_path / "q"
    cal = _fake_qlib(q)
    ind = tmp_path / "ind.csv"
    pd.DataFrame({"code": ["600000", "000001", "300750"], "sector": ["801780", "801780", "801730"]}).to_csv(ind, index=False)
    out = Q.build_standard_dir(q, ind, tmp_path / "out", start="2020-01-01", stock_start="2020-01-01", log=lambda *a: None)
    ma = pd.read_csv(out / "market_amount.csv")
    # 399300 不计入；300750 第 100 天的错误成交额被剔除；千元 → 元
    assert ma["amount"].iloc[5] == 3 * 1e5 * 1000
    assert ma["amount"].iloc[100] == 2 * 1e5 * 1000
    sec = pd.read_csv(out / "sector_daily.csv", dtype={"code": str})
    assert set(sec["code"]) == {"801780", "801730"}
    st = pd.read_parquet(out / "stock_daily.parquet")
    st["code"] = st["code"].astype(str)
    assert "399300" not in set(st["code"])
    t = st.set_index(["code", "date"])["tier"].astype(str)
    assert t.loc[("600000", cal[10])] == "龙头"
    assert t.loc[("000001", cal[10])] == "尾部" and t.loc[("000001", cal[300])] == "二线"   # 2020-06 起进入中证500
    idx = pd.read_csv(out / "index_daily.csv", dtype={"code": str})
    assert {"000300", "ALLA", "MICRO"} <= set(idx["code"])


def test_industry_tables_cover_sw1():
    assert set(EM_TO_SW1.values()) <= set(SW1_NAMES)
    assert set(SW2014_TO_SW1.values()) <= set(SW1_NAMES)


def test_parse_hybk(tmp_path):
    p = tmp_path / "hybk.ini"
    p.write_text("[银行]\n0,600000\n1,000001\n[半导体]\n0,688981\n", encoding="utf-8")
    df = parse_hybk(p)
    assert list(df["code"]) == ["600000", "000001", "688981"]
    assert df.set_index("code").loc["688981", "em_industry"] == "半导体"


def test_date_clusters_span_is_capped():
    cal = pd.bdate_range("2020-01-01", periods=500)
    d = cal[np.arange(0, 400, 10)]  # 每 10 天一个事件，连成一串
    cl = stats.date_clusters(d, 20, cal)
    # 旧做法会串成 1 簇；簇跨度封顶 20 日后约 400/30 ≈ 14 簇
    assert len(set(cl)) >= 12
