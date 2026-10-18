from __future__ import annotations

from typing import Any, Callable, Sequence

from .._types import AttrDict
from ..errors import TradingViewError
from ..quote.fields import QuoteData
from ..quote.quote_session import QuoteSubscription
from .operation import (
    OperationOptions,
    Watcher,
    WatchHandlers,
    _get_handler,
    run_operation,
    start_watcher,
    validate_symbol,
)

QuoteOptions = dict[str, Any]
QuoteQuery = dict[str, Any]
QuotesQuery = dict[str, Any]
QuoteHandlers = dict[str, Any]


def _validate_symbols(symbols: Any) -> list[str]:
    if not isinstance(symbols, (list, tuple)) or len(symbols) == 0:
        raise TradingViewError("INVALID_ARGUMENT", "symbols must be a non-empty array")
    seen: list[str] = []
    for s in symbols:
        v = validate_symbol(s)
        if v not in seen:
            seen.append(v)
    return seen


class QuoteWatcher(Watcher):
    def __init__(self, base: Watcher, get_latest: Callable[[], AttrDict]) -> None:
        super().__init__(base.stop, base.closed, lambda: base.is_active)
        self._get_latest = get_latest

    @property
    def latest(self) -> AttrDict:
        return self._get_latest()


async def get_quotes(
    query: QuotesQuery | Sequence[str] | None = None,
    **kwargs: Any,
) -> AttrDict:
    """Gets quotes for several symbols at once, keyed by symbol."""
    if isinstance(query, (list, tuple)):
        options: dict[str, Any] = {"symbols": list(query), **kwargs}
    else:
        options = {**(query or {}), **kwargs}

    symbols = _validate_symbols(options.get("symbols"))

    def _start(ctx: Any) -> Callable[[], None]:
        session = ctx.client.create_quote_session({"fields": options.get("fields")})
        results = AttrDict()
        pending = len(symbols)

        for sym in symbols:
            sub = session.subscribe(sym, {"session": options.get("session")})
            sub.on("error", ctx.reject)

            def _on_loaded(s: str = sym, subscription: QuoteSubscription = sub) -> None:
                nonlocal pending
                results[s] = subscription.data
                pending -= 1
                if pending == 0:
                    ctx.resolve(results)

            sub.once("loaded", _on_loaded)

        return session.delete

    return await run_operation(options, f"getQuotes({', '.join(symbols)})", _start)


getQuotes = get_quotes


async def get_quote(
    query: QuoteQuery | str | None = None,
    **kwargs: Any,
) -> QuoteData:
    """Gets the current quote of a symbol (last price, change, volume...)."""
    if isinstance(query, str):
        options: dict[str, Any] = {"symbol": query, **kwargs}
    else:
        options = {**(query or {}), **kwargs}
    symbol = validate_symbol(options.get("symbol"))
    quotes = await get_quotes({**options, "symbols": [symbol]})
    return quotes[symbol]


getQuote = get_quote


async def watch_quotes(
    query: QuotesQuery | Sequence[str],
    handlers: Any = None,
    **kwargs: Any,
) -> QuoteWatcher:
    """Streams quotes for one or more symbols. Call stop() when finished."""
    options = {"symbols": list(query), **kwargs} if isinstance(query, (list, tuple)) else {**(query or {}), **kwargs}
    on_data = _get_handler(handlers, "onData", "on_data")
    if not callable(on_data):
        raise TradingViewError("INVALID_ARGUMENT", "onData must be a function")
    symbols = _validate_symbols(options.get("symbols"))

    latest = AttrDict()

    def _start(ctx: Any) -> Callable[[], None]:
        session = ctx.client.create_quote_session({"fields": options.get("fields")})
        settled: set[str] = set()
        errors: list[TradingViewError] = []
        loaded = 0

        def settle(symbol: str, ok: bool) -> None:
            nonlocal loaded
            if symbol in settled:
                return
            settled.add(symbol)
            if ok:
                loaded += 1
            if len(settled) < len(symbols):
                return
            if loaded == 0:
                ctx.fail(errors[0])
            else:
                for err in errors:
                    ctx.warn(err)
                ctx.ready()

        subscriptions: list[QuoteSubscription] = []
        for symbol in symbols:
            sub = session.subscribe(symbol, {"session": options.get("session")})

            def _on_sub_data(quote: QuoteData, changes: QuoteData, sym: str = symbol) -> None:
                latest[sym] = quote
                if not ctx.is_active():
                    return
                try:
                    on_data(sym, quote, changes)
                except BaseException as err:
                    ctx.warn(TradingViewError("CALLBACK_ERROR", "onData callback threw", cause=err))

            def _on_sub_loaded(sym: str = symbol) -> None:
                settle(sym, True)

            def _on_sub_error(err: TradingViewError, sym: str = symbol) -> None:
                if err.code == "DISCONNECTED":
                    return
                if len(settled) < len(symbols) and sym not in settled:
                    errors.append(err)
                    settle(sym, False)
                else:
                    ctx.warn(err)

            sub.on("data", _on_sub_data)
            sub.on("loaded", _on_sub_loaded)
            sub.on("error", _on_sub_error)
            subscriptions.append(sub)

        def _cleanup() -> None:
            for s in subscriptions:
                s.close()
            session.delete()

        return _cleanup

    return await start_watcher(
        options,
        f"watchQuotes({', '.join(symbols)})",
        handlers,
        _start,
        lambda base: QuoteWatcher(base, lambda: AttrDict(latest)),
    )


watchQuotes = watch_quotes
