from __future__ import annotations

from typing import Any, Callable

from ..chart.types import SymbolInfo
from .operation import run_operation, validate_symbol

SymbolInfoQuery = dict[str, Any]


async def get_symbol_info(
    query: SymbolInfoQuery | str | None = None,
    **kwargs: Any,
) -> SymbolInfo:
    """Resolves a symbol: exchange, currency, session, price scale, type..."""
    if isinstance(query, str):
        options: dict[str, Any] = {"symbol": query, **kwargs}
    else:
        options = {**(query or {}), **kwargs}
    symbol = validate_symbol(options.get("symbol"))

    def _start(ctx: Any) -> Callable[[], None]:
        chart = ctx.client.create_chart()
        chart.on("error", ctx.reject)
        chart.on("symbolLoaded", ctx.resolve)
        chart.set_market(
            symbol,
            {
                "count": 1,
                "session": options.get("session"),
                "currency": options.get("currency"),
            },
        )
        return chart.delete

    return await run_operation(options, f"getSymbolInfo({symbol})", _start)


getSymbolInfo = get_symbol_info
