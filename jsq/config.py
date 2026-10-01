"""全局配置：标的、K线周期、手续费、出场方式等。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

INTERVAL_MINUTES = {
    "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}
INTERVAL_MS = {k: v * 60_000 for k, v in INTERVAL_MINUTES.items()}

# 默认标的：2026-09 在币安历史数据站核实存在的 USDT 永续合约。
# 注意 SPXUSDT 是 SPX6900 meme 币、DIAUSDT 是 DIA 预言机代币，都不是美股指数，已排除。
# 运行 `python -m jsq discover --save` 可重新探测并写入 symbols.txt（优先于此列表）。
DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT",
    # 贵金属：PAXG 历史最长（2025-03 起），可做黄金长样本参照
    "XAUUSDT", "PAXGUSDT", "XAUTUSDT", "XAGUSDT", "XPTUSDT", "XPDUSDT",
    # 能源：CL=WTI 原油，BZ=布伦特原油
    "CLUSDT", "BZUSDT", "NATGASUSDT",
    # 美股 / ETF
    "SPYUSDT", "QQQUSDT", "IWMUSDT", "AAPLUSDT", "MSFTUSDT", "NVDAUSDT", "GOOGLUSDT", "AMZNUSDT",
    "METAUSDT", "TSLAUSDT", "NFLXUSDT", "AMDUSDT", "AVGOUSDT", "ORCLUSDT", "INTCUSDT", "BABAUSDT",
    "COINUSDT", "MSTRUSDT", "HOODUSDT", "PLTRUSDT", "CRCLUSDT",
]
SYMBOLS_FILE = Path("symbols.txt")

# discover 用来识别非加密标的的关键字（baseAsset 精确匹配）
TRADFI_KEYWORDS = {
    "贵金属": {"XAU", "XAG", "XPT", "XPD", "PAXG", "XAUT", "GOLD", "SILVER"},
    "能源": {"OIL", "WTI", "BRENT", "CL", "BZ", "USOIL", "UKOIL", "NG", "NATGAS"},
    "美股/ETF": {
        "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "NFLX", "AMD",
        "INTC", "COIN", "MSTR", "HOOD", "PLTR", "CRCL", "AVGO", "ORCL", "BABA", "SPY",
        "QQQ", "SPX", "NDX", "US500", "US100", "IWM", "DIA", "GLD", "SLV", "USO",
    },
}

DEFAULT_INTERVAL = "1h"
DEFAULT_START = "2023-01-01"
DATA_DIR = Path("data")
RESULTS_DIR = Path("results")

# 预测力分析的前瞻周期（小时）
IC_HORIZONS_H = [1, 4, 12, 24, 72]

# 出场方式：ATR 用的是当前 K 线周期的 ATR(14)。max_hold_h 为最长持仓小时数。
# 所有方式都会在信号反转/消失时离场，持仓时间因此不固定（几小时到几天）。
EXIT_PROFILES = {
    "sig":     dict(),                                   # 只按信号进出
    "sl3":     dict(stop_atr=3.0),                       # 3ATR 止损
    "sl3tp6":  dict(stop_atr=3.0, tp_atr=6.0),           # 3ATR 止损 + 6ATR 止盈
    "trail4":  dict(trail_atr=4.0),                      # 4ATR 移动止损
    "sl4_24h": dict(stop_atr=4.0, max_hold_h=24),        # 止损 + 最多拿 1 天
    "sl4_72h": dict(stop_atr=4.0, max_hold_h=72),        # 止损 + 最多拿 3 天
}


@dataclass
class BacktestConfig:
    fee: float = 0.0005          # 单边手续费（币安 USDT 合约 taker 0.05%）
    slippage: float = 0.0002     # 单边滑点估计
    folds: int = 4               # 滚动样本外（OOS）窗口数
    initial_train_frac: float = 0.4  # 第一个训练窗口占全样本比例
    min_trades: int = 8          # 训练窗口内少于该交易数的参数不参与选优
    atr_period: int = 14
    exit_profiles: dict = field(default_factory=lambda: dict(EXIT_PROFILES))

    @property
    def cost(self) -> float:
        return self.fee + self.slippage


def bar_hours(interval: str) -> float:
    return INTERVAL_MINUTES[interval] / 60.0


def load_symbols(arg: str | None) -> list[str]:
    """--symbols 优先，其次 symbols.txt，最后默认列表。"""
    if arg:
        return [s.strip().upper() for s in arg.split(",") if s.strip()]
    if SYMBOLS_FILE.exists():
        syms = [ln.split("#")[0].strip().upper() for ln in SYMBOLS_FILE.read_text().splitlines()]
        syms = [s for s in syms if s]
        if syms:
            return syms
    return list(DEFAULT_SYMBOLS)
