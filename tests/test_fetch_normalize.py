"""akshare 返回格式 → 标准格式 的转换（不联网；列名取自 akshare 源码）。"""

import pandas as pd

from ashare_lab.data import fetch_akshare as F


def test_normalize_sw_hist():
    raw = pd.DataFrame({
        "代码": ["801080", "801080"], "日期": ["2024-01-02", "2024-01-03"],
        "收盘": ["3000.5", "3010.1"], "开盘": [1, 1], "最高": [1, 1], "最低": [1, 1],
        "成交量": [1, 1], "成交额": ["1234.5", "2345.6"],
    })
    out = F.normalize_sw_hist(raw, "801080")
    assert list(out.columns) == ["date", "code", "name", "close", "amount"]
    assert out["name"].iloc[0] == "电子"
    assert out["close"].iloc[1] == 3010.1


def test_normalize_index_hist():
    raw = pd.DataFrame({"日期": ["2024-01-02"], "开盘": [1.0], "收盘": [2.0], "最高": [3.0], "最低": [0.5],
                        "成交量": [10], "成交额": [100.0], "振幅": [0], "涨跌幅": [0], "涨跌额": [0], "换手率": [0]})
    out = F.normalize_index_hist(raw, "000985")
    assert out.iloc[0]["close"] == 2.0 and out.iloc[0]["amount"] == 100.0


def test_normalize_stock_hist_and_empty():
    raw = pd.DataFrame({"日期": ["2024-01-02"], "股票代码": ["000001"], "开盘": [1], "收盘": [10.5], "最高": [1],
                        "最低": [1], "成交量": [1], "成交额": [5e8], "振幅": [0], "涨跌幅": [0], "涨跌额": [0], "换手率": [1.25]})
    out = F.normalize_stock_hist(raw, "000001")
    assert out.iloc[0]["turnover"] == 1.25
    assert F.normalize_stock_hist(pd.DataFrame(), "000001").empty


def test_normalize_industry_clf_maps_prefix_to_sw1():
    raw = pd.DataFrame({"symbol": ["000001", "600519", "300750"],
                        "start_date": ["2021-07-30", "2021-07-30", "2021-07-30"],
                        "industry_code": ["480101", "340501", "630701"], "update_time": ["", "", ""]})
    out = F.normalize_industry_clf(raw).set_index("code")
    assert out.loc["000001", "sector"] == "801780"   # 银行
    assert out.loc["600519", "sector"] == "801120"   # 食品饮料
    assert out.loc["300750", "sector"] == "801730"   # 电力设备


def test_sw_prefix_table_covers_all_sw1():
    from ashare_lab.data.market import SW1_NAMES
    assert set(F.SW_PREFIX_TO_INDEX.values()) == set(SW1_NAMES)


def test_normalize_profit_and_bond():
    raw = pd.DataFrame({"股票代码": ["1"], "净利润-净利润": ["-3.5e8"], "最新公告日期": ["2024-04-20"]})
    out = F.normalize_profit(raw, "2023-12-31")
    assert out.iloc[0]["code"] == "000001" and out.iloc[0]["net_profit"] < 0
    bond = pd.DataFrame({"日期": ["2024-01-02", "2024-01-02"], "中国国债收益率10年": [2.5, 2.5], "中国国债收益率2年": [2.0, 2.0]})
    assert len(F.normalize_bond(bond)) == 1
