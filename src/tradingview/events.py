from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import Callable
from typing import Any

Listener = Callable[..., Any]
AnyListener = Callable[..., Any]
Unsubscribe = Callable[[], None]


def _log_error(*args: Any) -> None:
    print(*args, file=sys.stderr)


class Emitter:
    """Small typed event emitter shared by clients, sessions and studies.

    Listener exceptions are reported without interrupting other listeners or
    crashing the host process. An `error` event without any listener is written
    to stderr instead of being silently dropped.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}
        self._any_listeners: list[AnyListener] = []

    def on(self, event: str, listener: Listener) -> Unsubscribe:
        """Adds a listener and returns a function that removes it."""
        lst = self._listeners.setdefault(event, [])
        if listener not in lst:
            lst.append(listener)
        return lambda: self.off(event, listener)

    def once(self, event: str, listener: Listener) -> Unsubscribe:
        """Adds a listener called at most once."""

        def wrapper(*args: Any) -> Any:
            self.off(event, wrapper)
            return listener(*args)

        return self.on(event, wrapper)

    def off(self, event: str, listener: Listener) -> None:
        """Removes a listener."""
        lst = self._listeners.get(event)
        if lst and listener in lst:
            lst.remove(listener)

    def on_any(self, listener: AnyListener) -> Unsubscribe:
        """Listens to every event; receives the event name first."""
        if listener not in self._any_listeners:
            self._any_listeners.append(listener)
        return lambda: self._any_listeners.remove(listener) if listener in self._any_listeners else None

    onAny = on_any

    def listener_count(self, event: str) -> int:
        """Number of listeners for an event (catch-all listeners excluded)."""
        return len(self._listeners.get(event, []))

    listenerCount = listener_count

    def _has_listeners(self, event: str) -> bool:
        return self.listener_count(event) > 0 or len(self._any_listeners) > 0

    hasListeners = _has_listeners

    def _remove_all_listeners(self) -> None:
        self._listeners.clear()
        self._any_listeners.clear()

    removeAllListeners = _remove_all_listeners

    def _emit(self, event: str, *args: Any) -> None:
        lst = self._listeners.get(event)
        if event == "error" and not lst and not self._any_listeners:
            _log_error("[tradingview]", *args)
            return
        for listener in list(lst or ()):
            self._call(lambda fn=listener: fn(*args))
        for listener in list(self._any_listeners):
            self._call(lambda fn=listener: fn(event, *args))

    emit = _emit

    @staticmethod
    def _call(fn: Callable[[], Any]) -> None:
        try:
            result = fn()
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(_await_and_log(result))
                    _ = task
                except RuntimeError:
                    asyncio.run(_await_and_log(result))
        except Exception as error:
            _log_error("[tradingview] Listener threw:", error)


async def _await_and_log(awaitable: Any) -> None:
    try:
        await awaitable
    except Exception as error:
        _log_error("[tradingview] Listener threw:", error)
