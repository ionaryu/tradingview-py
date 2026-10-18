from __future__ import annotations

import math
import re
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from .request import HttpOptions, request

MarketType = str
MarketSearchResult = AttrDict
SearchMarketsOptions = dict[str, Any]
TechnicalRating = AttrDict
TechnicalAnalysisPeriod = str
TechnicalAnalysis = AttrDict

_ORIGIN = {"origin": "https://www.tradingview.com"}
_TA_PERIODS: list[str] = ["1", "5", "15", "60", "240", "1D", "1W", "1M"]
_TA_INDICATORS: list[str] = ["Recommend.Other", "Recommend.All", "Recommend.MA"]


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


async def search_markets(
    query: str,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[MarketSearchResult]:
    """Searches markets by keywords, `EXCHANGE:` prefix or `EXCHANGE:SYMBOL`."""
    opts = {**(options or {}), **kwargs}
    parts = query.upper().split(":")
    text = parts[1] if len(parts) == 2 else query.upper()
    exchange = opts.get("exchange") if opts.get("exchange") is not None else (parts[0] if len(parts) == 2 else None)

    res = await request(
        "https://symbol-search.tradingview.com/symbol_search/v3/",
        {
            "query": {
                "text": text,
                "exchange": exchange,
                "search_type": opts.get("type") or "",
                "start": opts.get("offset", 0),
                "country": opts.get("country"),
                "sector": opts.get("sector"),
            },
            "headers": _ORIGIN,
        },
        opts,
    )
    data = res.data
    status = res.status
    if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
        raise TradingViewError("HTTP_ERROR", f"Unexpected market search response (HTTP {status})", {"details": data})

    out: list[MarketSearchResult] = []
    for s in data["symbols"]:
        short_exchange = str(s.get("exchange") or "").split(" ")[0]
        symbol = re.sub(r"</?em>", "", str(s.get("symbol") or ""))
        prefix = s.get("prefix")
        out.append(
            AttrDict(
                {
                    "id": f"{prefix}:{symbol}" if prefix else f"{short_exchange.upper()}:{symbol}",
                    "exchange": short_exchange,
                    "fullExchange": s.get("exchange"),
                    "symbol": symbol,
                    "description": re.sub(r"</?em>", "", str(s.get("description") or "")),
                    "type": s.get("type"),
                    "currency": s.get("currency_code"),
                    "country": s.get("country"),
                }
            )
        )
    return out


searchMarkets = search_markets


async def get_technical_analysis(
    symbol: str,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> TechnicalAnalysis | None:
    """Gets technical ratings for every period from the TradingView scanner."""
    opts = {**(options or {}), **kwargs}
    columns = [
        name if period == "1D" else f"{name}|{period}"
        for period in _TA_PERIODS
        for name in _TA_INDICATORS
    ]
    res = await request(
        "https://scanner.tradingview.com/global/scan",
        {
            "method": "POST",
            "json": {"symbols": {"tickers": [symbol]}, "columns": columns},
        },
        opts,
    )
    data = res.data
    rows = data.get("data") if isinstance(data, dict) else None
    first_row = rows[0] if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict) else None
    values = first_row.get("d") if first_row else None
    if not isinstance(values, list):
        return None

    result = AttrDict()
    for index, value in enumerate(values):
        col = columns[index]
        parts = col.split("|")
        name = parts[0]
        period = parts[1] if len(parts) > 1 else "1D"
        key = name.split(".")[-1]
        if period not in result:
            result[period] = AttrDict()
        scaled = _js_round(float(value or 0) * 1000.0) / 500.0
        result[period][key] = int(scaled) if scaled.is_integer() else scaled
    return result


getTechnicalAnalysis = get_technical_analysis
