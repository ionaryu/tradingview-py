from __future__ import annotations

from typing import Any

from .candles import CandleHandlers, CandleSourceWorker, MarketDataProvider, WatchCandlesQuery, watch_candles
from .operation import ConnectionOptions


class TradingViewProvider:
    """Default candle source backed by TradingView, with optional connection defaults."""

    def __init__(self, connection: ConnectionOptions | None = None, **kwargs: Any) -> None:
        self._connection: dict[str, Any] = {**(connection or {}), **kwargs}

    async def watch_candles(
        self, query: WatchCandlesQuery, handlers: CandleHandlers
    ) -> CandleSourceWorker:
        return await watch_candles({**self._connection, **(query or {})}, handlers)

    watchCandles = watch_candles


__all__ = [
    "CandleSourceWorker",
    "MarketDataProvider",
    "TradingViewProvider",
]
