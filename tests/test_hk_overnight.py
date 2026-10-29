import numpy as np
import pandas as pd

from jsq import hk_overnight as ho


def _frame():
    """周三、周四、周五、下周一四个港股交易日。正股收盘：100 → 101 → 99 → 100；
    周四收盘后合约夜里涨到 +2%（08:59），周五开盘正股只跳空 +0.5%，合约开盘后回落。"""
    idx = pd.date_range("2026-08-05 00:00", "2026-08-10 23:59", freq="1min", tz="Asia/Hong_Kong")
    hm = idx.hour * 60 + idx.minute
    day = idx.strftime("%Y-%m-%d")
    closes = {"2026-08-05": 100.0, "2026-08-06": 101.0, "2026-08-07": 99.0, "2026-08-10": 100.0}
    opens = {"2026-08-05": 100.0, "2026-08-06": 100.5, "2026-08-07": 101.5, "2026-08-10": 99.5}
    index = np.full(len(idx), np.nan)
    last = 100.0
    for i, (d, m) in enumerate(zip(day, hm)):
        if d in closes and 570 <= m <= 970:          # 09:30–16:10 交易时段：开盘价 → 收盘价线性，加小波动
            f = (m - 570) / 400
            last = opens[d] + (closes[d] - opens[d]) * f + 0.2 * np.sin(i)
            if m == 970:
                last = closes[d]
        index[i] = last
    perp = index.copy()
    # 周四 16:10 收盘后 → 周五 09:29：合约从 101 涨到 103.02（+2%），开盘后回到 102
    thu_close = (day == "2026-08-06") & (hm > 970)
    fri_pre = (day == "2026-08-07") & (hm < 570)
    perp[thu_close] = 101.0 + 2.02 * (hm[thu_close] - 970) / (1440 - 970)
    perp[fri_pre] = 103.02
    fri_open = (day == "2026-08-07") & (hm >= 571) & (hm <= 720)
    perp[fri_open] = 102.0
    df = pd.DataFrame({"open": perp, "high": perp, "low": perp, "close": perp, "volume": 1.0,
                       "quote_volume": 1.0, "index": index}, index=idx.tz_convert("UTC"))
    df.attrs["symbol"] = "TESTUSDT"
    return df


def test_overnight_table_values():
    t = ho.overnight_table(_frame())
    row = t[t["day"] == "2026-08-06"].iloc[0]
    assert row["next_day"] == "2026-08-07" and not row["weekend"]
    assert abs(row["day_chg"] - 0.01) < 1e-9                    # 101 / 100 - 1
    assert abs(row["pm_08:59"] - 0.02) < 1e-6                   # 合约夜里 +2%
    assert row["open_jump"] < 0                                 # 开盘那一下合约回落
    fri = t[t["day"] == "2026-08-07"]
    assert len(fri) == 1 and bool(fri.iloc[0]["weekend"])       # 周五 → 下周一，跨周末


def test_advice_and_reference_close():
    assert ho.advise_overnight(0.025, 8 * 60 + 58).startswith("做空信号：")
    assert ho.advise_overnight(0.015, 8 * 60 + 58).startswith("做空信号（幅度一般）")
    assert "拿到 11:59" in ho.advise_overnight(0.025, 8 * 60 + 58)
    assert "08:59 做空" in ho.advise_overnight(0.015, 22 * 60)
    assert "不要抄底" in ho.advise_overnight(-0.02, 9 * 60)
    assert "别在开盘前追空" in ho.advise_overnight(-0.02, 9 * 60)
    assert "没有信号" in ho.advise_overnight(0.003, 9 * 60)
    assert "偏多" in ho.advise_baba(0.01) and "偏空" in ho.advise_baba(-0.01)
    hk = "Asia/Hong_Kong"
    assert ho.reference_close(pd.Timestamp("2026-08-07 17:00", tz=hk)).strftime("%Y-%m-%d") == "2026-08-07"
    assert ho.reference_close(pd.Timestamp("2026-08-07 15:00", tz=hk)).strftime("%Y-%m-%d") == "2026-08-06"
    assert ho.reference_close(pd.Timestamp("2026-08-10 08:50", tz=hk)).strftime("%Y-%m-%d") == "2026-08-07"
    assert ho.reference_close(pd.Timestamp("2026-08-09 12:00", tz=hk)).strftime("%Y-%m-%d") == "2026-08-07"


def test_preopen_rule_uses_only_0859_information():
    # 构造：08:59 前没涨，08:59 之后才涨 —— 规则不能触发（避免用到 08:59 之后的信息）
    t = pd.DataFrame({"symbol": "X", "day": ["2026-08-0%d" % i for i in range(1, 10)], "day_chg": 0.0,
                      "pm_08:59": 0.0, "pm_09:29": 0.05, "open_jump": -0.02, "after_1159": 0.0,
                      "pm_18:00": 0.0, "ref_overnight": 0.0})
    r = ho.preopen_rules(t, None, "2026-08-05")
    assert not r["rule"].str.startswith("夜里涨").any()
