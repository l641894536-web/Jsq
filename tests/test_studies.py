"""在合成数据上跑全部研究：
1) 流程能跑通、报告能生成；
2) 方法能找回事先埋入的规律（检验力）；
3) 在“什么都没埋”的数据上不乱报（误报率）。
"""

import numpy as np
import pandas as pd
import pytest

from ashare_lab.config import load_config
from ashare_lab.data.market import load_csv_dir
from ashare_lab.data.synthetic import make_synthetic
from ashare_lab.studies import a_lifecycle, b_crowding, c_crash, d_style, e_diffusion, f_regime, g_exit, h_decompose, i_portfolio
from ashare_lab.studies.common import Panels

FAST = {"common.n_perm": 400, "common.n_boot": 400}
MODULES = [a_lifecycle, b_crowding, c_crash, d_style, e_diffusion, f_regime, g_exit, h_decompose, i_portfolio]


@pytest.fixture(scope="module")
def planted():
    data, truth = make_synthetic(seed=7, stocks_per_sector=12)
    return Panels(data, load_config(overrides=FAST)), truth


@pytest.fixture(scope="module")
def results(planted):
    P, _ = planted
    return {m.__name__.split(".")[-1]: m.run(P) for m in MODULES}


def test_all_studies_produce_reports(results, tmp_path):
    for name, res in results.items():
        assert res.findings, name
        assert res.tables, name
        md = res.to_markdown()
        assert "合成数据" in md
        path = res.save(tmp_path)
        assert path.exists()
    assert any((tmp_path / "csv").iterdir())


def test_lifecycle_recovers_planted_tmt_mainlines(planted):
    P, truth = planted
    ep = a_lifecycle.detect_episodes(P)
    planted_eps = truth["episodes"]
    tmt = planted_eps[planted_eps["sector"].isin(["S01", "S02", "S03", "S04"])
                      & (planted_eps["peak"] >= P.study_start)]
    found = 0
    for _, e in tmt.iterrows():
        cand = ep[ep["代码"] == e["sector"]]
        gap = (cand["相对顶部"] - e["peak"]).abs().dt.days
        if (gap <= 45).any():
            found += 1
    assert found / len(tmt) >= 0.75, f"只找回 {found}/{len(tmt)} 轮埋入的主线"


def test_lifecycle_phases_are_ordered(planted):
    P, _ = planted
    ep = a_lifecycle.detect_episodes(P)
    done = ep[ep["_peak_ok"] & ep["首次超额"].notna()]
    assert (done["谷底"] < done["首次超额"]).all()
    assert (done["首次超额"] <= done["相对顶部"]).all()
    acc = done[done["加速"].notna()]
    assert (acc["首次超额"] <= acc["加速"]).all()


def test_crowding_finds_high_share_events(results):
    fam = results["b_crowding"].table("绝对阈值：穿越后未来超额（主题组合合并）")
    assert (fam["阈值"] == 0.40).any()
    assert fam["n"].max() > 0
    assert {"q值", "证据", "独立簇"} <= set(fam.columns)


def test_crash_study_labels_and_features(results):
    res = results["c_crash"]
    out = res.table("结果分布：机会 / 中性 / 趋势结束")
    assert out["事件数"].sum() > 0
    ratios = out[["机会比例", "中性比例", "趋势结束比例"]].sum(axis=1)
    assert np.allclose(ratios.dropna(), 1.0)


def test_diffusion_recovers_planted_order(results):
    t = results["e_diffusion"].table("扩散顺序的假设检验（跨主线波段）")
    h1 = t[t["假设"].str.startswith("H-E1")].iloc[0]
    assert h1["证据"].startswith(("A", "B")), h1


def test_regime_study_walk_forward_uses_only_past(planted):
    P, _ = planted
    strats = pd.DataFrame(f_regime.build_strategies(P))
    labels = f_regime.regime_labels(P)["均线法"]
    years = [2019, 2020]
    out1, picks1 = f_regime.walk_forward(strats, labels, years)
    # 篡改 2020 年及以后的数据，不应改变 2019 年的选择与收益
    strats2 = strats.copy()
    strats2.loc[strats2.index.year >= 2020] *= -5
    out2, picks2 = f_regime.walk_forward(strats2, labels, years)
    m = out1.index.year == 2019
    pd.testing.assert_series_equal(out1[m], out2[m])
    assert picks1[picks1["年份"] == 2019].equals(picks2[picks2["年份"] == 2019])


def test_null_data_has_few_false_discoveries():
    data, _ = make_synthetic(seed=11, null=True, stocks_per_sector=6)
    P = Panels(data, load_config(overrides=FAST))
    total = strong = 0
    for m in (b_crowding, c_crash, d_style, e_diffusion, g_exit, h_decompose):
        for t in m.run(P).tables:
            if "证据" in t.df.columns:
                g = t.df["证据"].astype(str)
                total += len(g)
                strong += int(g.str.startswith(("A", "B")).sum())
    assert total > 50
    assert strong / total <= 0.05, f"零假设数据上 A/B 级比例 {strong}/{total}"


def test_csv_roundtrip_loader(tmp_path):
    data, _ = make_synthetic(seed=3, with_stocks=True, stocks_per_sector=4)
    data.to_csv_dir(tmp_path)
    cfg = load_config()
    loaded = load_csv_dir(tmp_path, cfg)
    assert loaded.sector_close.shape == data.sector_close.shape
    np.testing.assert_allclose(loaded.sector_close.to_numpy(), data.sector_close.to_numpy(), rtol=1e-10)
    assert set(loaded.index_close.columns) == set(data.index_close.columns)
    assert loaded.stocks["code"].nunique() == data.stocks["code"].nunique()
    loaded.groups = data.groups
    res = a_lifecycle.run(Panels(loaded, cfg))
    assert res.findings


def test_exit_rules_trailing_stop_and_fixed_hold():
    from types import SimpleNamespace
    dates = pd.bdate_range("2020-01-01", periods=400)
    path = np.r_[np.linspace(1.0, 1.5, 101), np.linspace(1.5, 1.2, 100)[1:], np.full(200, 1.2)]
    rs = pd.DataFrame({"x": path}, index=dates)
    P = SimpleNamespace(rs=rs, share_pct=pd.DataFrame({"x": 0.5}, index=dates),
                        data=SimpleNamespace(dates=dates), cfg={"exit": {"entry_crowd_pct": 0.95}})
    rules = {"固定持有50日": 50, "回撤10%": ("trail", 0.10)}
    out = g_exit.simulate(P, "x", 0, rules, lag=1, window=250)
    t0 = 1
    assert out["固定持有50日"] == pytest.approx(path[t0 + 50] / path[t0] - 1)
    # 高点 1.5 在第 100 日，回撤到 1.35 以下的第一天确认，次日退出
    hit = int(np.flatnonzero(path[101:] <= 1.35)[0]) + 101
    assert out["回撤10%#天数"] == hit + 1 - t0
    assert out["回撤10%"] == pytest.approx(path[hit + 1] / path[t0] - 1)


def test_h2_and_h3_tables(results):
    res = results["h_decompose"]
    t2 = res.table("H2 占比创 99% 分位后的跑输：控制动量后还剩多少（H-B5）")
    assert {"配对差", "未配对差", "证据"} <= set(t2.columns)
    t3 = res.table("H3 次日确认规律的异质性（各分组内：次日续跌 − 次日收涨 的趋势结束比例差）")
    assert set(t3["拆分"]) >= {"跌幅档", "时期"}


def test_portfolio_weights_and_blacklists(planted):
    P, _ = planted
    ev1, black1 = i_portfolio.r1_blacklist(P)
    # 回避名单 = 事件后 60 个交易日内（含当日）
    code = ev1.sum().idxmax()
    first = ev1.index[ev1[code].to_numpy()][0]
    i = P.data.dates.get_loc(first)
    assert black1[code].iloc[i] and black1[code].iloc[i + 59] and not black1[code].iloc[i - 1]
    w = i_portfolio.eq_weights(pd.DataFrame({"a": [True, True], "b": [True, False]}))
    assert w.iloc[0].tolist() == [0.5, 0.5] and w.iloc[1].tolist() == [1.0, 0.0]


def test_monitor_and_scoreboard(tmp_path):
    from ashare_lab.monitor import append_log, scoreboard, snapshot
    data, _ = make_synthetic(seed=5, with_stocks=False)
    P = Panels(data, load_config(overrides={**FAST, "oos.start": "2020-01-01"}))
    res, log = snapshot(P)
    assert res.findings and not log.empty and log["signal_id"].is_unique
    path = tmp_path / "signals_log.csv"
    assert append_log(log, path) == len(log)
    assert append_log(log, path) == 0          # 同一信号只记一次
    sb = scoreboard(P, path)
    assert any(f.startswith("R1") for f in sb.findings)
