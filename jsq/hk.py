"""港股合约（币安 24 小时交易）与港股正股交易时段的错位研究。

港交所时间（香港时间 = UTC+8，无夏令时）：
  09:00-09:20 开盘前竞价（09:15 后不能撤单）  09:20 竞价撮合，开盘价确定
  09:30-12:00 上午连续交易   12:00-13:00 午休   13:00-16:00 下午连续交易
  16:00-16:10 收市竞价，收盘价确定
币安合约 24 小时交易；指数价格（indexPriceKlines）跟随正股，休市时基本不动。
所以：合约价 ÷ 指数价 - 1 = 休市期间合约对下一次开盘的“预先定价”。
"""
from __future__ import annotations

import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HK_SYMBOLS = ["ZHIPUUSDT", "MINIMAXUSDT", "HK1810USDT", "HK0700USDT", "TENCENTUSDT", "MEITUANUSDT",
              "POPMARTUSDT", "BYDUSDT", "KUAISHOUUSDT", "HK0625USDT", "HK0992USDT"]
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DAILY = "https://data.binance.vision/data/futures/um/daily"
KINDS = {"klines": "klines", "index": "indexPriceKlines"}


def _days_available(session, sym: str, kind: str) -> list[str]:
    r = session.get(S3, params={"prefix": f"data/futures/um/daily/{KINDS[kind]}/{sym}/1m/"}, timeout=60)
    return sorted(set(re.findall(r"-1m-(\d{4}-\d{2}-\d{2})\.zip<", r.text)))


def _get_day(session, sym, kind, day) -> pd.DataFrame | None:
    url = f"{DAILY}/{KINDS[kind]}/{sym}/1m/{sym}-1m-{day}.zip"
    for _ in range(3):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]), header=None, dtype=str)
            if not str(df.iloc[0, 0]).isdigit():
                df = df.iloc[1:]
            t = pd.to_numeric(df[0])
            t = t.where(t < 1e14, t // 1000)
            out = pd.DataFrame({"t": t.astype("int64"), "open": pd.to_numeric(df[1]), "high": pd.to_numeric(df[2]),
                                "low": pd.to_numeric(df[3]), "close": pd.to_numeric(df[4])})
            if kind == "klines":
                out["volume"] = pd.to_numeric(df[5])
                out["quote_volume"] = pd.to_numeric(df[7])
            return out
        except requests.RequestException:
            continue
    return None


def update(session, sym: str, data_dir: Path, workers: int = 12) -> dict:
    out = {}
    for kind in KINDS:
        p = Path(data_dir) / f"{sym}_1m_{kind}.csv"
        old = pd.read_csv(p) if p.exists() else pd.DataFrame()
        days = _days_available(session, sym, kind)
        if len(old):
            last = pd.Timestamp(int(old["t"].max()), unit="ms").strftime("%Y-%m-%d")
            days = [d for d in days if d >= last]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            parts = [x for x in ex.map(lambda d: _get_day(session, sym, kind, d), days) if x is not None]
        df = pd.concat([old] + parts, ignore_index=True) if parts or len(old) else pd.DataFrame()
        if len(df):
            df = df.drop_duplicates("t", keep="last").sort_values("t")
            df.to_csv(p, index=False)
        out[kind] = len(df)
    return out


def load(sym: str, data_dir: Path) -> pd.DataFrame:
    k = pd.read_csv(Path(data_dir) / f"{sym}_1m_klines.csv")
    i = pd.read_csv(Path(data_dir) / f"{sym}_1m_index.csv")
    df = k.merge(i[["t", "close"]].rename(columns={"close": "index"}), on="t", how="left")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("t"), unit="ms", utc=True)).as_unit("ns")
    df.attrs["symbol"] = sym
    return df


POST = ["09:31", "09:35", "09:45", "10:00", "10:30", "11:59", "15:59"]


def daily_table(df: pd.DataFrame) -> pd.DataFrame:
    """每个港股交易日一行。价格都取该分钟 K 线（香港时间）：
    prev_close_idx/perp —— 上一交易日 16:10 收市竞价后的指数 / 合约
    p_0859, p_0920, p_0929 —— 竞价前、竞价撮合后、连续交易开始前一刻的合约价
    open_idx —— 09:30 那分钟指数的开盘价（≈ 正股开盘价 = 竞价成交价）
    post_* —— 开盘后各时点的合约价
    """
    h = df.index.tz_convert("Asia/Hong_Kong")
    key = pd.Series(h.strftime("%Y-%m-%d %H:%M"), index=df.index)
    by = df.assign(key=key.values).set_index("key")
    days = sorted(set(h[h.weekday < 5].strftime("%Y-%m-%d")))
    rows, prev = [], None

    def px(day, hm, col="close"):
        k = f"{day} {hm}"
        return float(by.at[k, col]) if k in by.index else np.nan

    for d in days:
        o = px(d, "09:30", "open")
        oi = by["index"].get(f"{d} 09:30")
        idx_open = float(df.loc[df.index[key.values == f"{d} 09:30"], "index"].iloc[0]) if oi is not None else np.nan
        # 交易日判定：09:30 后 30 分钟指数确实在动
        seg = by.loc[[f"{d} 09:{m:02d}" for m in range(31, 60) if f"{d} 09:{m:02d}" in by.index], "index"]
        traded = len(seg) > 20 and seg.pct_change().abs().mean() > 2e-4
        if not traded:
            continue
        # 用前一分钟指数 close 与本分钟指数（open 近似）估计开盘价：取 09:30 分钟指数的 open 列不可得时用 close
        row = {"day": d, "p_0919": px(d, "09:19"), "idx_0931": px(d, "09:31", "index"),
               "p_0859": px(d, "08:59"), "p_0920": px(d, "09:20"), "p_0921": px(d, "09:21"), "p_0929": px(d, "09:29"),
               "open_idx": idx_open, "idx_0929": px(d, "09:29", "index"), "close_idx": px(d, "16:10", "index"),
               "perp_close": px(d, "16:10")}
        for hm in POST:
            row[f"post_{hm}"] = px(d, hm)
        if prev is not None:
            row["prev_close_idx"] = prev["close_idx"]
            row["prev_close_perp"] = prev["perp_close"]
            rows.append(row)
        prev = row
    t = pd.DataFrame(rows)
    if not len(t):
        return t
    t["symbol"] = df.attrs.get("symbol")
    t["gap"] = t["open_idx"] / t["prev_close_idx"] - 1                     # 正股真实跳空
    t["perp_overnight"] = t["p_0859"] / t["prev_close_perp"] - 1           # 合约在休市期间已经走的
    t["perp_to_0929"] = t["p_0929"] / t["prev_close_perp"] - 1
    t["resid_0920"] = t["open_idx"] / t["p_0920"] - 1                      # 竞价价 vs 竞价后合约价：尚未反映的部分
    t["resid_0929"] = t["open_idx"] / t["p_0929"] - 1
    t["perp_0921_0931"] = t["post_09:31"] / t["p_0921"] - 1
    t["auction_jump"] = t["p_0921"] / t["p_0919"] - 1                    # 09:20 竞价撮合时合约的反应
    t["basis_0931"] = t["post_09:31"] / t["idx_0931"] - 1                 # 开盘后合约相对正股的偏离
    for hm in POST[1:]:
        t[f"after_{hm}"] = t[f"post_{hm}"] / t["post_09:31"] - 1           # 开盘后漂移（从 09:31 起算）
    return t


def strategies(t: pd.DataFrame, cost: float, k: float = 0.003) -> pd.DataFrame:
    """开盘前后几种做法的每笔净收益。cost 为单边成本（手续费 + 滑点）。只用当时已知的信息。"""
    rows = []

    def add(name, desc, ret, mask=None):
        r = ret if mask is None else ret[mask]
        r = r.replace([np.inf, -np.inf], np.nan).dropna() - 2 * cost
        if len(r) < 8:
            return
        sd = r.std(ddof=1)
        rows.append({"strategy": name, "desc": desc, "trades": len(r), "win_rate": (r > 0).mean(),
                     "exp_bps": r.mean() * 1e4, "t": r.mean() / sd * np.sqrt(len(r)) if sd > 0 else 0,
                     "avg_win_bps": r[r > 0].mean() * 1e4, "avg_loss_bps": r[r <= 0].mean() * 1e4,
                     "symbols": t.loc[r.index, "symbol"].nunique()})

    entry = t["p_0921"]
    # A. 你现在的做法：看竞价方向（跳空方向）09:21 在合约上开仓。只取跳空 >1.5% 的日子，方向不会被第一分钟噪音弄反
    sg, big_gap = np.sign(t["gap"]), t["gap"].abs() > 0.015
    for hm in ["09:31", "10:00", "11:59", "15:59"]:
        add(f"A_gap_{hm}", f"按竞价跳空方向 09:21 开仓，持有到 {hm}（跳空含开盘第一分钟，偏乐观）",
            sg * (t[f"post_{hm}"] / entry - 1), big_gap)
    # A'. 同样的方向，但 09:31 才进场（此时跳空已完全已知，没有前视偏差）
    for hm in ["10:00", "11:59", "15:59"]:
        add(f"A2_gap_{hm}", f"按跳空方向 09:31 开仓，持有到 {hm}", sg * t[f"after_{hm}"], big_gap)
    # B. 09:20 竞价撮合时合约的跳动是否延续
    sj, big_j = np.sign(t["auction_jump"]), t["auction_jump"].abs() > k
    for hm in ["09:31", "09:45", "10:00", "11:59"]:
        add(f"B_jump_{hm}", f"09:20 撮合时合约跳动 >{k:.1%}，09:21 顺势开仓，持有到 {hm}",
            sj * (t[f"post_{hm}"] / entry - 1), big_j)
        add(f"B_jumpfade_{hm}", f"09:20 撮合时合约跳动 >{k:.1%}，09:21 反向开仓，持有到 {hm}",
            -sj * (t[f"post_{hm}"] / entry - 1), big_j)
    # C. 开盘后合约与正股的偏离会不会收敛（09:31 起）
    sb, big_b = np.sign(t["basis_0931"]), t["basis_0931"].abs() > k
    for hm in ["09:45", "10:00", "10:30", "11:59"]:
        add(f"C_basis_{hm}", f"09:31 合约比正股高(低) >{k:.1%} 就做空(多)合约，持有到 {hm}", -sb * t[f"after_{hm}"], big_b)
    # D. 合约隔夜涨跌，开盘后延续还是回吐（09:31 起）
    so = np.sign(t["perp_to_0929"])
    for hm in ["10:00", "11:59", "15:59"]:
        add(f"D_fade_{hm}", f"09:31 反向做合约隔夜涨跌，持有到 {hm}", -so * t[f"after_{hm}"])
        add(f"D_follow_{hm}", f"09:31 顺着合约隔夜涨跌做，持有到 {hm}", so * t[f"after_{hm}"])
    return pd.DataFrame(rows)


def prepricing(t: pd.DataFrame) -> pd.DataFrame:
    """正股跳空里，合约在各时点已经走掉了多少（回归斜率 + 剩余缺口占比）。"""
    rows = []
    for sym, g in list(t.groupby("symbol")) + [("全部", t)]:
        g = g.dropna(subset=["gap", "perp_overnight", "perp_to_0929", "resid_0920", "resid_0929"])
        if len(g) < 8:
            continue
        def slope(x, y):
            x, y = g[x].to_numpy(), g[y].to_numpy()
            return float(np.polyfit(y, x, 1)[0]), float(np.corrcoef(x, y)[0, 1] ** 2)
        b0859, r0859 = slope("perp_overnight", "gap")
        b0929, r0929 = slope("perp_to_0929", "gap")
        rows.append({"symbol": sym, "days": len(g), "abs_gap_bps": g["gap"].abs().mean() * 1e4,
                     "priced_0859": b0859, "r2_0859": r0859, "priced_0929": b0929, "r2_0929": r0929,
                     "left_0920_bps": g["resid_0920"].abs().mean() * 1e4, "left_0929_bps": g["resid_0929"].abs().mean() * 1e4,
                     "same_dir_0929": float((np.sign(g["perp_to_0929"]) == np.sign(g["gap"])).mean())})
    return pd.DataFrame(rows)


def remaining_gap(auction_chg: float, perp_move: float) -> float:
    """竞价相对昨收的涨跌 vs 合约自昨收已走的涨跌 -> 合约还没反映的部分（正 = 合约还该涨）。"""
    return (1 + auction_chg) / (1 + perp_move) - 1


def advise_preopen(remaining: float, auction_chg: float, th: float = 0.003) -> str:
    if abs(remaining) < th:
        return "合约已基本反映竞价结果，开盘追单没有优势"
    if np.sign(remaining) == np.sign(auction_chg):
        side = "做多" if remaining > 0 else "做空"
        return f"合约还差 {remaining:+.2%} 没走到竞价价，顺竞价方向{side}仍有空间（历史上这类日子胜率约 68%）"
    side = "跌" if auction_chg < 0 else "涨"
    return (f"合约已经{side}过头 {abs(remaining):.2%}（比竞价走得更远），不要追；"
            f"历史上这类日子追单平均亏损，开盘后合约常往回走")


# 价差收敛规则在这些标的上历史无效（大盘蓝筹、定价已很有效），实时提示时标注出来
WEAK_SYMBOLS = {"HK0700USDT", "TENCENTUSDT", "POPMARTUSDT"}


def advise_open(basis: float, th: float = 0.003, symbol: str = "") -> str:
    weak = "（该标的历史上此规则无效，仅供参考）" if symbol in WEAK_SYMBOLS else ""
    if basis > th:
        return (f"合约比正股贵 {basis:.2%}：可做空合约，持有到 11:59~13:30；只设 3~5% 的宽止损，"
                f"靠仓位控制风险{weak}")
    if basis < -th:
        return f"合约比正股便宜 {abs(basis):.2%}：可做多合约，持有到 11:59~13:30（这类日子较少）{weak}"
    return "合约与正股价差在 ±0.3% 内，无信号"


def robustness(P: dict, cost: float, split: str) -> dict[str, pd.DataFrame]:
    """价差收敛规则的稳健性：参数网格（前后两段）、止损影响、按标的、午休时段。"""
    grid = []
    for sig in ["09:31", "09:33", "09:35"]:
        for ex in ["10:30", "11:59", "13:30"]:
            for th in [0.002, 0.003, 0.005]:
                T = pd.concat([basis_trades(p, s, sig, ex, th, cost) for s, p in P.items()], ignore_index=True)
                if not len(T):
                    continue
                f, a, b = (summarize_trades(x) for x in (T, T[T.day < split], T[T.day >= split]))
                grid.append({"signal": sig, "exit": ex, "threshold": th, "trades": f["trades"], "exp_bps": f["exp_bps"],
                             "t": f["t"], "win_rate": f["win_rate"], "exp_first_half": a.get("exp_bps"),
                             "exp_second_half": b.get("exp_bps"), "t_second_half": b.get("t")})
    stops = []
    for stop in [None, 0.01, 0.02, 0.03, 0.05]:
        T = pd.concat([basis_trades(p, s, "09:31", "11:59", 0.003, cost, stop=stop) for s, p in P.items()],
                      ignore_index=True)
        m = summarize_trades(T)
        stops.append({"stop": stop or 0, "stopped_share": T["stopped"].mean(), "exp_bps": m["exp_bps"], "t": m["t"],
                      "win_rate": m["win_rate"]})
    T = pd.concat([basis_trades(p, s, "09:31", "11:59", 0.003, cost) for s, p in P.items()], ignore_index=True)
    by_sym = T.groupby("symbol").apply(lambda x: pd.Series(summarize_trades(x))).reset_index()
    decomp = pd.DataFrame([{"gross_bps": T["gross"].mean() * 1e4, "stock_part_bps": T["stock_ret"].mean() * 1e4,
                            "basis_part_bps": T["basis_change"].mean() * 1e4,
                            "mae_median_bps": T["mae"].median() * 1e4, "mae_p90_bps": T["mae"].quantile(0.9) * 1e4}])
    lunch = []
    for ex in ["14:00", "15:59"]:
        L = pd.concat([basis_trades(p, s, "13:01", ex, 0.003, cost) for s, p in P.items()], ignore_index=True)
        if len(L):
            m = summarize_trades(L)
            lunch.append({"signal": "13:01", "exit": ex, "trades": m["trades"], "exp_bps": m["exp_bps"], "t": m["t"]})
    return {"grid": pd.DataFrame(grid), "stops": pd.DataFrame(stops), "by_symbol": by_sym,
            "decomposition": decomp, "lunch": pd.DataFrame(lunch)}


def panel(df: pd.DataFrame, start: str = "09:00", end: str = "16:10") -> dict[str, pd.DataFrame]:
    """港股交易日 × 分钟（香港时间）的价格面板：close/high/low 为合约，index 为指数（≈正股）。"""
    h = df.index.tz_convert("Asia/Hong_Kong")
    day = np.asarray(h.strftime("%Y-%m-%d"))
    hm = np.asarray(h.strftime("%H:%M"))
    keep = (hm >= start) & (hm <= end) & (h.weekday < 5)
    x = df.loc[keep, ["close", "high", "low", "index"]].assign(day=day[keep], hm=hm[keep])
    out = {c: x.pivot_table(index="day", columns="hm", values=c, aggfunc="last") for c in ["close", "high", "low", "index"]}
    # 交易日：09:31-09:59 指数有明显波动
    cols = [c for c in out["index"].columns if "09:31" <= c <= "09:59"]
    act = out["index"][cols].pct_change(axis=1).abs().mean(axis=1)
    days = act[act > 2e-4].index
    return {k: v.loc[v.index.intersection(days)] for k, v in out.items()}


def basis_trades(p: dict, sym: str, sig_hm: str, exit_hm: str, th: float, cost: float,
                 stop: float | None = None) -> pd.DataFrame:
    """在 sig_hm 收盘看 合约/正股-1，超过 ±th 反向开仓（下一分钟按 sig_hm 收盘价近似成交），exit_hm 收盘平仓。
    stop：相对开仓价的止损比例（用 1 分钟最高/最低价判断，触发按止损价成交）。"""
    c, hi, lo, ix = p["close"], p["high"], p["low"], p["index"]
    if sig_hm not in c or exit_hm not in c:
        return pd.DataFrame()
    basis = c[sig_hm] / ix[sig_hm] - 1
    side = -np.sign(basis).where(basis.abs() > th)
    path_cols = [m for m in c.columns if sig_hm < m <= exit_hm]
    rows = []
    for d, sd in side.dropna().items():
        entry = c.at[d, sig_hm]
        if not np.isfinite(entry):
            continue
        exit_px = c.at[d, exit_hm]
        hi_p, lo_p = hi.loc[d, path_cols].to_numpy(), lo.loc[d, path_cols].to_numpy()
        adverse = (np.nanmax(hi_p) / entry - 1) if sd < 0 else (1 - np.nanmin(lo_p) / entry)
        favorable = (1 - np.nanmin(lo_p) / entry) if sd < 0 else (np.nanmax(hi_p) / entry - 1)
        ret = sd * (exit_px / entry - 1)
        stopped = False
        if stop is not None and adverse >= stop:   # 持仓期间最不利价格触及止损
            ret, stopped = -stop, True
        stock_ret = ix.at[d, exit_hm] / ix.at[d, sig_hm] - 1
        rows.append({"symbol": sym, "day": d, "side": sd, "basis": basis[d], "ret": ret - 2 * cost,
                     "gross": ret, "mae": adverse, "mfe": favorable, "stopped": stopped,
                     "stock_ret": sd * stock_ret, "basis_change": sd * ((exit_px / ix.at[d, exit_hm]) / (entry / ix.at[d, sig_hm]) - 1)})
    return pd.DataFrame(rows)


def summarize_trades(t: pd.DataFrame) -> dict:
    if not len(t):
        return {"trades": 0}
    r = t["ret"]
    sd = r.std(ddof=1)
    return {"trades": len(r), "symbols": t["symbol"].nunique(), "win_rate": (r > 0).mean(),
            "exp_bps": r.mean() * 1e4, "t": r.mean() / sd * np.sqrt(len(r)) if sd > 0 else 0,
            "avg_win_bps": r[r > 0].mean() * 1e4, "avg_loss_bps": r[r <= 0].mean() * 1e4,
            "mae_med_bps": t["mae"].median() * 1e4, "mae_p90_bps": t["mae"].quantile(0.9) * 1e4,
            "sym_pos": float((t.groupby("symbol")["ret"].mean() > 0).mean())}
