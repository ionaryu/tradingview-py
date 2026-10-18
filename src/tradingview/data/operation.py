from __future__ import annotations

import asyncio
from datetime import datetime
import math
import sys
from typing import Any, Callable, Generic, TypeVar

from .._types import AbortSignal, AttrDict
from ..client.client import TradingViewClient
from ..errors import TradingViewError, to_trading_view_error

T = TypeVar("T")
W = TypeVar("W")

ConnectionOptions = dict[str, Any]
OperationOptions = dict[str, Any]
WatchHandlers = dict[str, Any]
Cleanup = Callable[[], Any] | None

DEFAULT_TIMEOUT_MS = 15_000


def _abort_error(signal: AbortSignal) -> TradingViewError:
    reason = getattr(signal, "reason", None)
    if isinstance(reason, BaseException):
        message = str(reason) or "Aborted"
    elif reason is not None:
        message = str(reason)
    else:
        message = "Aborted"
    return TradingViewError("ABORTED", message, cause=reason)


def validate_timeout(timeout_ms: float | int | None) -> float:
    value = DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise TradingViewError("INVALID_ARGUMENT", "timeoutMs must be a positive number")
    return float(value)


validateTimeout = validate_timeout


def validate_symbol(symbol: Any) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise TradingViewError("INVALID_ARGUMENT", "symbol is required")
    return symbol.strip()


validateSymbol = validate_symbol


def throw_if_aborted(signal: AbortSignal | None = None) -> None:
    if signal is not None and getattr(signal, "aborted", False):
        raise _abort_error(signal)


throwIfAborted = throw_if_aborted


class _Connection:
    def __init__(self, client: TradingViewClient, release: Callable[[], Any]) -> None:
        self.client = client
        self.release = release


def _connect(options: dict[str, Any]) -> _Connection:
    provided = options.get("client")
    if provided is not None:
        if provided.is_closed:
            raise TradingViewError("INVALID_STATE", "The provided client is closed")

        async def _noop() -> None:
            return None

        return _Connection(provided, _noop)

    client_opts = dict(options.get("clientOptions") or options.get("client_options") or {})
    if "credentials" in options and options["credentials"] is not None:
        client_opts["credentials"] = options["credentials"]
    client = TradingViewClient(client_opts)
    return _Connection(client, client.close)


class OperationContext(AttrDict, Generic[T]):
    client: TradingViewClient
    resolve: Callable[[T], None]
    reject: Callable[[Any], None]


def run_operation(
    options: dict[str, Any] | None,
    description: str,
    start: Callable[[OperationContext[T]], Cleanup],
) -> asyncio.Future[T]:
    """Runs a one-shot operation with timeout, abort and guaranteed cleanup."""
    opts = dict(options or {})
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[T] = loop.create_future()

    try:
        timeout_ms = validate_timeout(
            opts.get("timeoutMs") if "timeoutMs" in opts else opts.get("timeout_ms")
        )
        throw_if_aborted(opts.get("signal"))
        connection = _connect(opts)
    except BaseException as err:
        result_future.set_exception(to_trading_view_error(err, "INVALID_ARGUMENT"))
        return result_future

    client = connection.client
    signal: AbortSignal | None = opts.get("signal")

    settled = False
    cleanup: Cleanup = None
    unsubscribers: list[Callable[[], None]] = []
    start_finished: asyncio.Future[None] = loop.create_future()
    timer_handle: asyncio.TimerHandle | None = None

    async def _settle(error: TradingViewError | None, value: Any) -> None:
        await start_finished
        try:
            if callable(cleanup):
                cleanup()
        except BaseException:
            pass
        try:
            await connection.release()
        except BaseException:
            pass
        if not result_future.done():
            if error is not None:
                result_future.set_exception(error)
            else:
                result_future.set_result(value)

    def finish(error: TradingViewError | None = None, value: Any = None) -> None:
        nonlocal settled
        if settled:
            return
        settled = True
        if timer_handle is not None:
            timer_handle.cancel()
        if signal is not None:
            signal.remove_event_listener("abort", on_abort)
        for off in unsubscribers:
            off()
        loop.create_task(_settle(error, value))

    def on_abort() -> None:
        if signal is not None:
            finish(_abort_error(signal))

    timer_handle = loop.call_later(
        timeout_ms / 1000.0,
        lambda: finish(TradingViewError("TIMEOUT", f"{description} timed out after {int(timeout_ms) if timeout_ms.is_integer() else timeout_ms} ms")),
    )

    if signal is not None:
        signal.add_event_listener("abort", on_abort, once=True)
    unsubscribers.append(client.on("error", lambda err: finish(err)))
    unsubscribers.append(
        client.on(
            "close",
            lambda *_: finish(TradingViewError("DISCONNECTED", f"Connection closed during {description}")),
        )
    )

    ctx = OperationContext(
        {
            "client": client,
            "resolve": lambda val: finish(None, val),
            "reject": lambda err: finish(to_trading_view_error(err)),
        }
    )

    try:
        cleanup = start(ctx)
    except BaseException as err:
        finish(to_trading_view_error(err, "INVALID_ARGUMENT"))
    finally:
        if not start_finished.done():
            start_finished.set_result(None)

    return result_future


runOperation = run_operation


class Watcher:
    """A running watcher."""

    def __init__(
        self,
        stop_fn: Callable[[], asyncio.Future[None]],
        closed_future: asyncio.Future[None],
        is_active_fn: Callable[[], bool],
    ) -> None:
        self._stop_fn = stop_fn
        self._closed = closed_future
        self._is_active_fn = is_active_fn

    def stop(self) -> asyncio.Future[None]:
        return self._stop_fn()

    @property
    def closed(self) -> asyncio.Future[None]:
        return self._closed

    @property
    def is_active(self) -> bool:
        return self._is_active_fn()

    @property
    def isActive(self) -> bool:
        return self._is_active_fn()

    async def __aenter__(self) -> Watcher:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.stop()


class WatchContext(AttrDict):
    client: TradingViewClient
    ready: Callable[[], None]
    fail: Callable[[Any], None]
    warn: Callable[[Any], None]
    isActive: Callable[[], bool]
    is_active: Callable[[], bool]


def _get_handler(handlers: Any, camel: str, snake: str) -> Callable[..., Any] | None:
    if isinstance(handlers, dict):
        fn = handlers.get(camel) or handlers.get(snake)
        return fn if callable(fn) else None
    fn = getattr(handlers, camel, None) or getattr(handlers, snake, None)
    return fn if callable(fn) else None


def start_watcher(
    options: dict[str, Any] | None,
    description: str,
    handlers: Any,
    start: Callable[[WatchContext], Cleanup],
    build: Callable[[Watcher], W],
) -> asyncio.Future[W]:
    """Starts a watcher. Resolves once ready() is called; rejects on timeout/abort/failure before that."""
    opts = dict(options or {})
    loop = asyncio.get_running_loop()
    start_promise: asyncio.Future[W] = loop.create_future()

    try:
        timeout_ms = validate_timeout(
            opts.get("timeoutMs") if "timeoutMs" in opts else opts.get("timeout_ms")
        )
        throw_if_aborted(opts.get("signal"))
        connection = _connect(opts)
    except BaseException as err:
        start_promise.set_exception(to_trading_view_error(err, "INVALID_ARGUMENT"))
        return start_promise

    client = connection.client
    signal: AbortSignal | None = opts.get("signal")

    active = True
    started = False
    cleanup: Cleanup = None
    start_finished: asyncio.Future[None] = loop.create_future()
    stop_promise: asyncio.Future[None] | None = None
    closed: asyncio.Future[None] = loop.create_future()
    unsubscribers: list[Callable[[], None]] = []
    timer_handle: asyncio.TimerHandle | None = None

    on_error = _get_handler(handlers, "onError", "on_error")

    def report(error: TradingViewError) -> None:
        try:
            if on_error is not None:
                on_error(error)
        except BaseException as listener_error:
            print("[tradingview] onError callback threw:", listener_error, file=sys.stderr)

    async def _do_stop() -> None:
        await start_finished
        try:
            if callable(cleanup):
                cleanup()
        except BaseException:
            pass
        try:
            await connection.release()
        except BaseException:
            pass
        if not closed.done():
            closed.set_result(None)

    def stop() -> asyncio.Future[None]:
        nonlocal active, stop_promise
        if stop_promise is not None:
            return stop_promise
        active = False
        if timer_handle is not None:
            timer_handle.cancel()
        if signal is not None:
            signal.remove_event_listener("abort", on_abort)
        for off in unsubscribers:
            off()
        stop_promise = loop.create_task(_do_stop())
        return stop_promise

    def fail(raw: Any) -> None:
        if not active:
            return
        error = to_trading_view_error(raw)
        closing = stop()
        if not started:
            def _reject_after_close(_fut: asyncio.Future[None]) -> None:
                if not start_promise.done():
                    start_promise.set_exception(error)

            closing.add_done_callback(_reject_after_close)
        else:
            report(error)

    base_watcher = Watcher(stop, closed, lambda: active)
    watcher = build(base_watcher)

    def on_abort() -> None:
        if signal is not None:
            fail(_abort_error(signal))

    timer_handle = loop.call_later(
        timeout_ms / 1000.0,
        lambda: fail(
            TradingViewError(
                "TIMEOUT",
                f"{description} timed out after {int(timeout_ms) if timeout_ms.is_integer() else timeout_ms} ms",
            )
        )
        if not started
        else None,
    )

    if signal is not None:
        signal.add_event_listener("abort", on_abort, once=True)
    unsubscribers.append(client.on("error", lambda err: fail(err)))
    unsubscribers.append(
        client.on(
            "close",
            lambda *_: fail(TradingViewError("DISCONNECTED", f"Connection closed during {description}")),
        )
    )

    def mark_ready() -> None:
        nonlocal started
        if not active or started:
            return
        started = True
        if timer_handle is not None:
            timer_handle.cancel()
        if not start_promise.done():
            start_promise.set_result(watcher)

    def warn(error: Any) -> None:
        if active:
            report(to_trading_view_error(error))

    ctx = WatchContext(
        {
            "client": client,
            "ready": mark_ready,
            "fail": fail,
            "warn": warn,
            "isActive": lambda: active,
            "is_active": lambda: active,
        }
    )

    try:
        cleanup = start(ctx)
    except BaseException as err:
        fail(err)
    finally:
        if not start_finished.done():
            start_finished.set_result(None)

    return start_promise


startWatcher = start_watcher


def to_unix_seconds(value: int | float | datetime | None, name: str) -> int | float | None:
    """Converts a datetime or Unix time (seconds) into Unix seconds."""
    if value is None:
        return None
    if isinstance(value, datetime):
        seconds: int | float = math.floor(value.timestamp())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value
    else:
        raise TradingViewError("INVALID_ARGUMENT", f"{name} must be a Date or Unix seconds")
    if not math.isfinite(seconds):
        raise TradingViewError("INVALID_ARGUMENT", f"{name} must be a Date or Unix seconds")
    return seconds


toUnixSeconds = to_unix_seconds
