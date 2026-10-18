from __future__ import annotations

import asyncio
from typing import Any, Callable, Protocol, Sequence

from .._types import AttrDict
from ..chart.types import Candle, SymbolInfo
from ..errors import TradingViewError
from .history import (
    ChartQuery,
    RangeQuery,
    load_history,
    no_data_error,
    open_market,
    plan_history,
    select_candles,
)
from .operation import (
    OperationOptions,
    Watcher,
    WatchHandlers,
    _get_handler,
    run_operation,
    start_watcher,
)

CandleQuery = dict[str, Any]
WatchCandlesQuery = dict[str, Any]
CandleHandlers = dict[str, Any]


class CandleSourceWorker(Protocol):
    @property
    def latest(self) -> Sequence[Candle]: ...
    async def stop(self) -> None: ...


class MarketDataProvider(Protocol):
    async def watchCandles(self, query: WatchCandlesQuery, handlers: Any) -> CandleSourceWorker: ...


class CandleWatcher(Watcher):
    def __init__(
        self,
        base: Watcher,
        get_latest: Callable[[], tuple[Candle, ...]],
        get_symbol_info: Callable[[], SymbolInfo | None],
    ) -> None:
        super().__init__(base.stop, base.closed, lambda: base.is_active)
        self._get_latest = get_latest
        self._get_symbol_info = get_symbol_info

    @property
    def latest(self) -> tuple[Candle, ...]:
        return self._get_latest()

    @property
    def symbol_info(self) -> SymbolInfo | None:
        return self._get_symbol_info()

    @property
    def symbolInfo(self) -> SymbolInfo | None:
        return self._get_symbol_info()


def _invoke_provider_watch(provider: Any, options: dict[str, Any], handlers: dict[str, Any]) -> Any:
    if isinstance(provider, dict):
        fn = provider.get("watchCandles") or provider.get("watch_candles")
    else:
        fn = getattr(provider, "watchCandles", None) or getattr(provider, "watch_candles", None)
    if not callable(fn):
        raise TradingViewError("INVALID_ARGUMENT", "Invalid MarketDataProvider")
    return fn(options, AttrDict(handlers))


def _invoke_worker_stop(worker: Any) -> Any:
    if isinstance(worker, dict):
        fn = worker.get("stop")
    else:
        fn = getattr(worker, "stop", None)
    if callable(fn):
        return fn()
    return None


def _get_worker_latest(worker: Any) -> Any:
    if isinstance(worker, dict):
        return worker.get("latest", ())
    return getattr(worker, "latest", ())


def _rejected_future(error: BaseException) -> asyncio.Future[Any]:
    fut = asyncio.get_running_loop().create_future()
    fut.set_exception(error)
    return fut


def get_candles(
    query: CandleQuery | str | None = None,
    provider: Any = None,
    **kwargs: Any,
) -> asyncio.Future[list[Candle]]:
    """Fetches candles once, oldest first, then releases every resource."""
    if isinstance(query, str):
        options: dict[str, Any] = {"symbol": query, **kwargs}
    else:
        options = {**(query or {}), **kwargs}

    try:
        plan = plan_history(options)
    except BaseException as err:
        return _rejected_future(err)

    if provider is not None:
        async def _via_provider() -> list[Candle]:
            snapshot: Sequence[Candle] = []

            def _on_data(candles: Sequence[Candle]) -> None:
                nonlocal snapshot
                snapshot = candles

            worker = await _invoke_provider_watch(
                provider, options, {"onData": _on_data, "on_data": _on_data}
            )
            try:
                source = snapshot if len(snapshot) > 0 else _get_worker_latest(worker)
                return list(source)
            finally:
                res = _invoke_worker_stop(worker)
                if asyncio.isfuture(res) or asyncio.iscoroutine(res):
                    await res

        return asyncio.ensure_future(_via_provider())

    def _start(ctx: Any) -> Callable[[], None]:
        chart = ctx.client.create_chart()
        chart.on("error", ctx.reject)

        def _on_done(info: Any) -> None:
            candles = select_candles(chart.candles, plan)
            if len(candles) == 0:
                ctx.reject(no_data_error(plan["symbol"], info))
            else:
                ctx.resolve(candles)

        load_history(chart, plan, True, _on_done)
        open_market(chart, plan)
        return chart.delete

    return run_operation(options, f"getCandles({plan['symbol']})", _start)


getCandles = get_candles


def watch_candles(
    query: WatchCandlesQuery | str,
    handlers: Any = None,
    provider: Any = None,
    **kwargs: Any,
) -> asyncio.Future[Any]:
    """Streams candles in real time. Resolves once initial history is loaded; call stop() when finished."""
    options = {"symbol": query, **kwargs} if isinstance(query, str) else {**(query or {}), **kwargs}
    try:
        on_data = _get_handler(handlers, "onData", "on_data")
        if not callable(on_data):
            raise TradingViewError("INVALID_ARGUMENT", "onData must be a function")
        plan = plan_history({**options, "from": None, "to": None})
    except BaseException as err:
        return _rejected_future(err)

    if provider is not None:
        res = _invoke_provider_watch(
            provider,
            options,
            handlers
            if isinstance(handlers, dict)
            else {"onData": on_data, "onError": _get_handler(handlers, "onError", "on_error")},
        )
        return asyncio.ensure_future(res) if asyncio.iscoroutine(res) else res

    latest: tuple[Candle, ...] = ()
    symbol_info: SymbolInfo | None = None

    def _start(ctx: Any) -> Callable[[], None]:
        nonlocal latest, symbol_info
        chart = ctx.client.create_chart()
        started = False

        def publish() -> None:
            nonlocal latest
            selected = select_candles(chart.candles, plan)
            latest = tuple(AttrDict(c) for c in selected)
            try:
                on_data(latest)
            except BaseException as err:
                ctx.warn(TradingViewError("CALLBACK_ERROR", "onData callback threw", cause=err))

        chart.on("error", lambda err: ctx.fail(err))

        def _on_symbol(info: SymbolInfo) -> None:
            nonlocal symbol_info
            symbol_info = info

        chart.on("symbolLoaded", _on_symbol)
        chart.on(
            "update",
            lambda changes: publish()
            if (started and ctx.is_active() and "$prices" in changes)
            else None,
        )

        def _on_done(info: Any) -> None:
            nonlocal started
            if len(chart.candles) == 0:
                ctx.fail(no_data_error(plan["symbol"], info))
                return
            started = True
            publish()
            ctx.ready()

        load_history(chart, plan, False, _on_done)
        open_market(chart, plan)
        return chart.delete

    return start_watcher(
        options,
        f"watchCandles({plan['symbol']})",
        handlers,
        _start,
        lambda base: CandleWatcher(base, lambda: latest, lambda: symbol_info),
    )


watchCandles = watch_candles
