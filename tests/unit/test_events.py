from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from tradingview.events import Emitter


class _DummyEmitter(Emitter):
    def fire(self, event: str, *args):
        self._emit(event, *args)


class TestEventsSuite:
    def test_supports_on_once_off_on_any_and_unsubscribe_functions(self):
        emitter = _DummyEmitter()
        seen: list[str] = []
        off = emitter.on("tick", lambda n: seen.append(f"on{n}"))
        emitter.once("tick", lambda n: seen.append(f"once{n}"))
        off_any = emitter.onAny(lambda event, *args: seen.append(f"any:{event}:{args[0]}"))
        emitter.fire("tick", 1)
        emitter.fire("tick", 2)
        off()
        off_any()
        emitter.fire("tick", 3)
        assert seen == ["on1", "once1", "any:tick:1", "on2", "any:tick:2"]
        assert emitter.listenerCount("tick") == 0
        assert emitter.listener_count("tick") == 0

    def test_logs_unhandled_errors_instead_of_dropping_them(self, monkeypatch):
        logged: list[tuple] = []
        monkeypatch.setattr("tradingview.events._log_error", lambda *args: logged.append(args))
        err = RuntimeError("boom")
        _DummyEmitter().fire("error", err)
        assert logged == [("[tradingview]", err)]

    async def test_handles_async_listener_rejections_including_once_and_catch_all(self, monkeypatch):
        emitter = _DummyEmitter()
        logged: list[tuple] = []
        monkeypatch.setattr("tradingview.events._log_error", lambda *args: logged.append(args))
        after = MagicMock()

        async def bad_on(_n):
            raise RuntimeError("async on")

        async def bad_once(_n):
            raise RuntimeError("async once")

        async def bad_any(_event, *_args):
            raise RuntimeError("async any")

        emitter.on("tick", bad_on)
        emitter.once("tick", bad_once)
        emitter.on_any(bad_any)
        emitter.on("tick", after)
        emitter.fire("tick", 1)
        await asyncio.sleep(0.02)
        assert len(logged) == 3
        after.assert_called_once_with(1)
        messages = [str(item[1]) for item in logged]
        assert "async on" in messages
        assert "async once" in messages
        assert "async any" in messages

    def test_isolates_throwing_listeners_from_the_emitter(self, monkeypatch):
        emitter = _DummyEmitter()
        after = MagicMock()
        logged: list[tuple] = []
        monkeypatch.setattr("tradingview.events._log_error", lambda *args: logged.append(args))

        def bad_sync(_n):
            raise RuntimeError("listener bug")

        emitter.on("tick", bad_sync)
        emitter.on("tick", after)
        emitter.fire("tick", 1)
        after.assert_called_once_with(1)
        assert len(logged) == 1
        assert logged[0][0] == "[tradingview] Listener threw:"
        assert str(logged[0][1]) == "listener bug"
