import numpy as np
import pandas as pd

from jsq import hk


def test_remaining_gap_and_advice():
    # 竞价 -2%，合约已跌 3% -> 合约跌过头，剩余为正（合约该往回涨）
    rem = hk.remaining_gap(-0.02, -0.03)
    assert rem > 0 and "过头" in hk.advise_preopen(rem, -0.02)
    rem = hk.remaining_gap(-0.03, -0.01)
    assert rem < 0 and "做空" in hk.advise_preopen(rem, -0.03)
    assert "无信号" in hk.advise_open(0.001) and "做空" in hk.advise_open(0.005)


def _fake_day_frame():
    # 两个交易日：指数在 09:30 才跳到开盘价，合约在夜里提前走了一部分
    idx = pd.date_range("2026-08-03 00:00", "2026-08-04 23:59", freq="1min", tz="Asia/Hong_Kong")
    n = len(idx)
    hm = idx.hour * 60 + idx.minute
    day2 = idx.day == 4
    index = np.where(day2 & (hm >= 570), 102.0, 100.0) + np.where((hm >= 570) & (hm < 960), np.sin(np.arange(n)) * 0.2, 0)
    perp = np.where(day2 & (hm >= 1), 101.0, 100.0)
    perp = np.where(day2 & (hm >= 570), 102.0, perp) + np.where((hm >= 570) & (hm < 960), np.sin(np.arange(n)) * 0.2, 0)
    df = pd.DataFrame({"open": perp, "high": perp, "low": perp, "close": perp, "volume": 1.0, "quote_volume": 1.0,
                       "index": index}, index=idx.tz_convert("UTC"))
    df.attrs["symbol"] = "TESTUSDT"
    return df


def test_daily_table_prepricing():
    t = hk.daily_table(_fake_day_frame())
    assert len(t) == 1
    r = t.iloc[0]
    assert abs(r["gap"] - 0.02) < 0.005          # 正股跳空约 +2%
    assert abs(r["perp_to_0929"] - 0.01) < 0.005  # 合约开盘前已走约 +1%
    assert r["resid_0929"] > 0                    # 还剩约 1% 没反映


def _panel_one_day(perp_0931=101.0, perp_exit=100.0, index_0931=100.0, index_exit=100.0, spike=None):
    cols = ["09:31", "09:32", "11:59"]
    close = pd.DataFrame([[perp_0931, perp_0931, perp_exit]], index=["2026-08-04"], columns=cols)
    high = close.copy()
    low = close.copy()
    if spike is not None:
        high.loc[:, "09:32"] = spike
    index = pd.DataFrame([[index_0931, index_0931, index_exit]], index=["2026-08-04"], columns=cols)
    return {"close": close, "high": high, "low": low, "index": index}


def test_basis_trades_direction_stop_and_decomposition():
    # 合约比正股贵 1%：做空；合约回到 100 -> 毛收益约 +0.99%，全部来自价差收敛
    t = hk.basis_trades(_panel_one_day(), "X", "09:31", "11:59", 0.003, cost=0.0)
    r = t.iloc[0]
    assert r["side"] == -1 and np.isclose(r["gross"], 1 / 101, atol=1e-6)
    assert abs(r["stock_ret"]) < 1e-12 and r["basis_change"] > 0
    # 偏离不够阈值：不交易
    assert hk.basis_trades(_panel_one_day(perp_0931=100.2), "X", "09:31", "11:59", 0.003, 0.0).empty
    # 持仓中最高价冲到 106（不利 ~5%）：3% 止损触发，按 -3% 计
    t = hk.basis_trades(_panel_one_day(spike=106.0), "X", "09:31", "11:59", 0.003, cost=0.0, stop=0.03)
    assert bool(t.iloc[0]["stopped"]) and np.isclose(t.iloc[0]["ret"], -0.03)


def test_micro_spread_and_one_sided_window():
    from jsq import hk_micro
    t0 = int(pd.Timestamp("2026-08-04 09:31:00", tz="Asia/Hong_Kong").timestamp() * 1000)
    rows = []
    for k in range(60):  # 每 5 秒一买一卖：买 100.1，卖 99.9 -> 有效价差约 20 基点
        rows.append([k, 100.1, 1.0, k, k, t0 + k * 5000, False])
        rows.append([k, 99.9, 1.0, k, k, t0 + k * 5000 + 1000, True])
    # 午休前窗口只有主动买：无法估计价差，但不能报错
    t1 = int(pd.Timestamp("2026-08-04 11:55:00", tz="Asia/Hong_Kong").timestamp() * 1000)
    rows += [[1000 + k, 100.0, 1.0, 0, 0, t1 + k * 1000, False] for k in range(10)]
    df = pd.DataFrame(rows, columns=["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
                                     "transact_time", "is_buyer_maker"])
    out = {r["window"]: r for r in hk_micro.trades_day(df)}
    assert abs(out["open"]["spread_bps"] - 20) < 0.5
    assert np.isnan(out["am_close"]["spread_bps"]) and out["am_close"]["trades"] == 10
