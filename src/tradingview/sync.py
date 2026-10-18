"""Synchronous convenience wrappers for one-shot Data and HTTP APIs."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Sequence, TypeVar

from .data import (
    get_candles as _async_get_candles,
    get_indicator_data as _async_get_indicator_data,
    get_quote as _async_get_quote,
    get_quotes as _async_get_quotes,
    get_symbol_info as _async_get_symbol_info,
)
from .http import (
    get_chart_token as _async_get_chart_token,
    get_drawings as _async_get_drawings,
    get_hotlist as _async_get_hotlist,
    get_indicator as _async_get_indicator,
    get_private_indicators as _async_get_private_indicators,
    get_screener as _async_get_screener,
    get_technical_analysis as _async_get_technical_analysis,
    get_user as _async_get_user,
    get_watchlists as _async_get_watchlists,
    login_user as _async_login_user,
    search_indicators as _async_search_indicators,
    search_markets as _async_search_markets,
)

T = TypeVar("T")


def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    async def _runner() -> Any:
        return await fn(*args, **kwargs)

    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if not loop_running:
        return asyncio.run(_runner())

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _runner())
        return future.result()


def get_candles(query: dict[str, Any] | str | None = None, provider: Any = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_candles, query, provider, **kwargs)


getCandles = get_candles


def get_quote(query: dict[str, Any] | str | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_quote, query, **kwargs)


getQuote = get_quote


def get_quotes(query: dict[str, Any] | Sequence[str] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_quotes, query, **kwargs)


getQuotes = get_quotes


def get_symbol_info(query: dict[str, Any] | str | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_symbol_info, query, **kwargs)


getSymbolInfo = get_symbol_info


def get_indicator_data(query: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_indicator_data, query, **kwargs)


getIndicatorData = get_indicator_data


def search_markets(query: str, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_search_markets, query, options, **kwargs)


searchMarkets = search_markets


def get_technical_analysis(id_str: str, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_technical_analysis, id_str, options, **kwargs)


getTechnicalAnalysis = get_technical_analysis


def search_indicators(query: str = "", options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_search_indicators, query, options, **kwargs)


searchIndicators = search_indicators


def get_indicator(id_str: str, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_indicator, id_str, options, **kwargs)


getIndicator = get_indicator


def get_private_indicators(credentials: dict[str, Any], options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_private_indicators, credentials, options, **kwargs)


getPrivateIndicators = getPrivateIndicators = get_private_indicators


def get_screener(query: dict[str, Any] | None = None, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_screener, query, options, **kwargs)


getScreener = get_screener


def get_watchlists(options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_watchlists, options, **kwargs)


getWatchlists = get_watchlists


def get_hotlist(query: dict[str, Any] | None = None, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_hotlist, query, options, **kwargs)


getHotlist = get_hotlist


def get_user(credentials: dict[str, Any], options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_user, credentials, options, **kwargs)


getUser = get_user


def login_user(options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_login_user, options, **kwargs)


loginUser = login_user


def get_chart_token(layout_id: str, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_chart_token, layout_id, options, **kwargs)


getChartToken = get_chart_token


def get_drawings(layout_id: str, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _run_sync(_async_get_drawings, layout_id, options, **kwargs)


getDrawings = get_drawings


__all__ = [
    "get_candles",
    "getCandles",
    "get_quote",
    "getQuote",
    "get_quotes",
    "getQuotes",
    "get_symbol_info",
    "getSymbolInfo",
    "get_indicator_data",
    "getIndicatorData",
    "search_markets",
    "searchMarkets",
    "get_technical_analysis",
    "getTechnicalAnalysis",
    "search_indicators",
    "searchIndicators",
    "get_indicator",
    "getIndicator",
    "get_private_indicators",
    "getPrivateIndicators",
    "get_screener",
    "getScreener",
    "get_watchlists",
    "getWatchlists",
    "get_hotlist",
    "getHotlist",
    "get_user",
    "getUser",
    "login_user",
    "loginUser",
    "get_chart_token",
    "getChartToken",
    "get_drawings",
    "getDrawings",
]
