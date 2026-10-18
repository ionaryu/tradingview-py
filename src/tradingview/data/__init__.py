"""
High-level data API: one-shot functions and watchers that manage
connections, sessions, timeouts and cleanup for you.
"""

from ..chart.strategy import summarize_strategy_report, summarizeStrategyReport
from ..errors import TradingViewError
from ..http import (
    get_hotlist,
    get_screener,
    get_technical_analysis,
    get_watchlists,
    getHotlist,
    getScreener,
    getTechnicalAnalysis,
    getWatchlists,
    search_indicators,
    search_markets,
    searchIndicators,
    searchMarkets,
)
from .candles import get_candles, getCandles, watch_candles, watchCandles
from .indicators import get_indicator_data, getIndicatorData, watch_indicator, watchIndicator
from .operation import DEFAULT_TIMEOUT_MS
from .provider import TradingViewProvider
from .quotes import get_quote, get_quotes, getQuote, getQuotes, watch_quotes, watchQuotes
from .symbols import get_symbol_info, getSymbolInfo

# Official JS public export keys for parity checks:
JS_EXPORTS = (
    "DEFAULT_TIMEOUT_MS",
    "TradingViewError",
    "TradingViewProvider",
    "getCandles",
    "getHotlist",
    "getIndicatorData",
    "getQuote",
    "getQuotes",
    "getScreener",
    "getSymbolInfo",
    "getTechnicalAnalysis",
    "getWatchlists",
    "searchIndicators",
    "searchMarkets",
    "summarizeStrategyReport",
    "watchCandles",
    "watchIndicator",
    "watchQuotes",
)

__all__ = [
    *JS_EXPORTS,
    "get_candles",
    "watch_candles",
    "get_quote",
    "get_quotes",
    "watch_quotes",
    "get_symbol_info",
    "get_indicator_data",
    "watch_indicator",
    "get_technical_analysis",
    "search_indicators",
    "search_markets",
    "summarize_strategy_report",
    "get_screener",
    "get_watchlists",
    "get_hotlist",
]
