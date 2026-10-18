import pytest

from tradingview.client.client import TradingViewClient
from tradingview.data.operation import runOperation, startWatcher
from tests.helpers.fake_server import FakeServer


def shared_client():
    server = FakeServer()
    return TradingViewClient({"transport": server.transport})


@pytest.mark.asyncio
async def test_runs_cleanup_before_resolving_one_shot_operation():
    client = shared_client()
    calls = 0

    def cleanup():
        nonlocal calls
        calls += 1

    try:
        def start(ctx):
            ctx.resolve(42)
            return cleanup

        value = await runOperation({"client": client}, "immediate", start)
        assert value == 42
        assert calls == 1
        assert client.isClosed is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_runs_cleanup_after_watcher_becomes_ready_synchronously():
    client = shared_client()
    calls = 0

    def cleanup():
        nonlocal calls
        calls += 1

    try:
        def start(ctx):
            ctx.ready()
            return cleanup

        watcher = await startWatcher({"client": client}, "immediate", {}, start, lambda base: base)
        await watcher.stop()
        await watcher.closed
        assert calls == 1
        assert client.isClosed is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_runs_cleanup_after_watcher_fails_synchronously():
    client = shared_client()
    calls = 0

    def cleanup():
        nonlocal calls
        calls += 1

    try:
        def start(ctx):
            ctx.fail(RuntimeError("startup failed"))
            return cleanup

        with pytest.raises(Exception, match="startup failed"):
            await startWatcher({"client": client}, "immediate", {}, start, lambda base: base)
        assert calls == 1
        assert client.isClosed is False
    finally:
        await client.close()
