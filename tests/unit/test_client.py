from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.helpers.fake_server import FakeServer, flush, until
from tradingview._types import FetchResponse
from tradingview.client import TradingViewClient
from tradingview.errors import TradingViewError
from tradingview.protocol import encode_frame, encode_packet

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
LIVE = json.loads((FIXTURES / "live-session.json").read_text(encoding="utf-8"))


def setup(options: dict | None = None):
    server = FakeServer()
    client = TradingViewClient({"transport": server.transport, **(options or {})})
    return server, client


class TestTradingViewClient:
    async def test_connects_with_browser_headers_and_anonymous_token_then_flushes_queue(self):
        server, client = setup({"server": "prodata", "headers": {"X-Test": "1"}})
        client.send("custom_method", ["a"])
        assert server.last.raw == []
        await client.ready
        assert server.last.request.url == "wss://prodata.tradingview.com/socket.io/websocket?from=chart&type=chart"
        assert server.last.request.origin == "https://www.tradingview.com"
        assert server.last.request.headers["X-Test"] == "1"
        assert "Mozilla" in server.last.request.headers["User-Agent"]
        assert server.last.raw == [
            encode_packet("set_auth_token", ["unauthorized_user_token"]),
            encode_packet("custom_method", ["a"]),
        ]
        assert client.isOpen is True
        assert client.isAuthenticated is True
        await client.close()

    async def test_uses_explicit_auth_token(self):
        server, client = setup({"authToken": "secret-token"})
        await client.ready
        assert server.last.sent[0] == {"m": "set_auth_token", "p": ["secret-token"]}
        await client.close()

    async def test_loads_auth_token_from_credentials_with_account_lookup(self):
        calls: list[tuple] = []

        async def mock_fetch(url: str, init: dict):
            calls.append((url, init))
            return FetchResponse('<script>{"id":1,"username":"me","auth_token":"from-account"}</script>')

        server, client = setup(
            {
                "credentials": {"session": "s", "signature": "sig"},
                "fetch": mock_fetch,
                "location": "https://fr.tradingview.com/",
            }
        )
        await client.ready
        assert len(calls) == 1
        assert calls[0][0] == "https://fr.tradingview.com/"
        assert calls[0][1]["headers"]["cookie"] == "sessionid=s;sessionid_sign=sig"
        assert calls[0][1]["redirect"] == "manual"
        assert server.last.sent[0] == {"m": "set_auth_token", "p": ["from-account"]}
        await client.close()

    async def test_fails_emits_auth_error_and_closes_when_credentials_rejected(self):
        async def mock_fetch(_url: str, _init: dict):
            return FetchResponse("no token here", status=200)

        server, client = setup({"credentials": {"session": "bad"}, "fetch": mock_fetch})
        errors: list[str] = []
        client.on("error", lambda err: errors.append(err.code))
        with pytest.raises(TradingViewError) as exc_info:
            await client.ready
        assert exc_info.value.code == "AUTH_ERROR"
        await until(lambda: client.isClosed)
        assert errors == ["AUTH_ERROR"]
        assert server.last.closed is True

    async def test_rejects_ready_without_logging_when_nobody_listens_and_passes_cause(self, monkeypatch):
        logged: list = []
        monkeypatch.setattr("tradingview.events._log_error", lambda *args: logged.append(args))

        async def mock_fetch(_url: str, _init: dict):
            return FetchResponse("no token")

        _, client = setup({"credentials": {"session": "bad"}, "fetch": mock_fetch})
        on_close = MagicMock()
        client.registerSession("cs_z", {"onPacket": lambda _p: None, "onClose": on_close})
        with pytest.raises(TradingViewError) as exc_info:
            await client.ready
        assert exc_info.value.code == "AUTH_ERROR"
        await until(lambda: client.isClosed)
        assert logged == []
        err_arg = on_close.call_args[0][0]
        assert err_arg.code == "DISCONNECTED"
        assert "Credentials error" in err_arg.message
        assert err_arg.cause.code == "AUTH_ERROR"

    async def test_answers_heartbeats_and_emits_hello_heartbeat_and_unrouted_packets(self):
        server, client = setup()
        events: list[str] = []
        client.onAny(lambda event, *_args: events.append(event))
        await client.ready
        server.last.push({"session_id": "srv", "protocol": "json"}, "~h~12", {"m": "unknown_packet", "p": ["nobody"]})
        assert server.last.heartbeats == [12]
        assert client.serverInfo.session_id == "srv"
        assert events == ["open", "ready", "hello", "heartbeat", "packet"]
        await client.close()

    async def test_routes_packets_to_registered_sessions(self):
        server, client = setup()
        received: list = []
        client.registerSession("cs_x", {"onPacket": lambda pkt: received.append(pkt)})
        await client.ready
        server.last.push({"m": "series_loading", "p": ["cs_x", "$prices", "s1"]})
        assert received == [{"m": "series_loading", "p": ["cs_x", "$prices", "s1"]}]
        await client.close()

    async def test_turns_protocol_error_into_error_event_and_closes(self):
        server, client = setup()
        await client.ready
        errors: list[TradingViewError] = []
        client.on("error", lambda err: errors.append(err))
        server.last.push({"m": "protocol_error", "p": ["wrong data"]})
        assert len(errors) == 1
        assert errors[0].code == "PROTOCOL_ERROR"
        assert errors[0].message == "Protocol error: wrong data"
        await until(lambda: client.isClosed)

    async def test_notifies_sessions_and_rejects_readiness_when_connection_drops(self):
        server = FakeServer()
        server.autoOpen = False
        client = TradingViewClient({"transport": server.transport})
        on_close = MagicMock()
        client.registerSession("cs_y", {"onPacket": lambda _p: None, "onClose": on_close})
        close_codes: list = []
        client.on("close", lambda code, _reason=None: close_codes.append(code))
        server.last.drop(1006, "gone")
        with pytest.raises(TradingViewError) as exc_info:
            await client.ready
        assert exc_info.value.code == "DISCONNECTED"
        assert close_codes == [1006]
        assert on_close.call_args[0][0].code == "DISCONNECTED"
        assert on_close.call_args[0][1] is False
        with pytest.raises(TradingViewError, match="closed"):
            client.send("late")

    async def test_times_out_if_connection_never_opens(self):
        server = FakeServer()
        server.autoOpen = False
        client = TradingViewClient({"transport": server.transport, "connectTimeoutMs": 15})
        client.on("error", lambda _e: None)
        with pytest.raises(TradingViewError) as exc_info:
            await client.ready
        assert exc_info.value.code == "TIMEOUT"

    async def test_close_is_idempotent_and_waits_for_socket_to_close(self):
        _, client = setup()
        await client.ready
        await asyncio.gather(client.close(), client.close())
        assert client.isClosed is True
        await client.close()

    async def test_logs_traffic_through_debug_function(self):
        lines: list[tuple] = []
        _, client = setup({"debug": lambda *args: lines.append(args)})
        await client.ready
        client.send("ping_me")
        await flush()
        assert any(line[0] == "send" for line in lines)
        await client.close()

    async def test_routes_captured_live_session_to_chart_and_quote_sessions(self):
        server, client = setup()
        chart_packets: list[str] = []
        quote_packets: list[str] = []
        client.registerSession("cs_fixture", {"onPacket": lambda p: chart_packets.append(p.m)})
        client.registerSession("qs_fixture", {"onPacket": lambda p: quote_packets.append(p.m)})
        await client.ready
        for message in LIVE["messages"]:
            server.last.handlers.onMessage(message)
        for expected in ("symbol_resolved", "timescale_update", "series_completed", "du", "symbol_error"):
            assert expected in chart_packets
        for expected in ("qsd", "quote_completed"):
            assert expected in quote_packets
        assert client.serverInfo.protocol == "json"
        await client.close()

    async def test_accepts_raw_frame_through_send(self):
        server, client = setup()
        await client.ready
        client.send("quote_fast_symbols", ["qs_1", "A"])
        assert server.last.raw[-1] == encode_frame({"m": "quote_fast_symbols", "p": ["qs_1", "A"]})
        await client.close()


class TestAccountLookupLifecycle:
    @pytest.mark.parametrize("ending", ["close", "timeout", "disconnect"])
    async def test_aborts_pending_authentication_without_secondary_auth_error(self, ending: str):
        captured_signal = None

        async def mock_fetch(_url: str, init: dict):
            nonlocal captured_signal
            captured_signal = init.get("signal")
            fut = asyncio.get_running_loop().create_future()
            if captured_signal is not None:
                captured_signal.add_event_listener(
                    "abort", lambda: fut.set_exception(captured_signal.reason) if not fut.done() else None
                )
            return await fut

        server, client = setup({"credentials": {"session": "fixture"}, "fetch": mock_fetch, "connectTimeoutMs": 25})
        errors: list[str] = []
        client.on("error", lambda err: errors.append(err.code))
        await asyncio.sleep(0)
        if ending == "close":
            await client.close()
        if ending == "disconnect":
            server.last.drop()
        with pytest.raises(TradingViewError) as exc_info:
            await client.ready
        assert exc_info.value.code == ("TIMEOUT" if ending == "timeout" else "DISCONNECTED")
        await until(lambda: client.isClosed)
        assert captured_signal is not None and captured_signal.aborted is True
        assert errors == (["TIMEOUT"] if ending == "timeout" else [])
        assert len(server.last.packets("set_auth_token")) == 0


class TestUnexpectedConnectionLoss:
    async def test_fails_and_terminates_connection_that_goes_silent(self):
        server, client = setup({"inactivityTimeoutMs": 80})
        errors: list[str] = []
        client.on("error", lambda err: errors.append(err.code))
        on_close = MagicMock()
        client.registerSession("cs_silent", {"onPacket": lambda _p: None, "onClose": on_close})
        closed_fut: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        client.on("close", lambda code, _r=None: closed_fut.set_result(code) if not closed_fut.done() else None)
        await client.ready
        for beat in range(1, 5):
            await asyncio.sleep(0.035)
            server.last.push(f"~h~{beat}")
        assert client.isOpen is True
        assert errors == []
        assert await closed_fut == 1006
        assert server.last.terminated is True
        assert errors == ["CONNECTION_ERROR"]
        assert on_close.call_count == 1
        err_arg, exp_arg = on_close.call_args[0]
        assert err_arg.code == "DISCONNECTED"
        assert "No data from the server" in err_arg.message
        assert err_arg.cause.code == "CONNECTION_ERROR"
        assert exp_arg is False

    @pytest.mark.parametrize("inactivity_timeout_ms", [0, math.inf, 2**40])
    async def test_keeps_silent_connection_open_when_disabled_or_large(self, inactivity_timeout_ms):
        server, client = setup({"inactivityTimeoutMs": inactivity_timeout_ms})
        await client.ready
        await asyncio.sleep(0.04)
        assert client.isOpen is True
        assert server.last.terminated is False
        await client.close()

    async def test_reports_socket_error_followed_by_close_once_as_connection_error(self):
        server, client = setup()
        errors: list[str] = []
        client.on("error", lambda err: errors.append(err.code))
        on_close = MagicMock()
        client.registerSession("cs_reset", {"onPacket": lambda _p: None, "onClose": on_close})
        await client.ready
        server.last.handlers.onError(RuntimeError("read ECONNRESET"))
        server.last.drop(1006, "")
        await until(lambda: client.isClosed)
        assert errors == ["CONNECTION_ERROR"]
        assert on_close.call_count == 1
        assert "ECONNRESET" in str(on_close.call_args[0][0].cause)
        assert on_close.call_args[0][1] is False
        await client.close()

    async def test_starts_fresh_connection_after_abrupt_loss_without_leaking_state(self):
        server = FakeServer()
        first = TradingViewClient({"transport": server.transport})
        await first.ready
        first.registerSession("cs_old", {"onPacket": lambda _p: None})
        server.last.drop()
        await until(lambda: first.isClosed)
        with pytest.raises(TradingViewError, match="closed"):
            first.send("late")
        await first.close()

        second = TradingViewClient({"transport": server.transport})
        await second.ready
        received: list[str] = []
        second.registerSession("cs_new", {"onPacket": lambda pkt: received.append(pkt.m)})
        server.last.push({"m": "series_loading", "p": ["cs_new"]}, {"m": "series_loading", "p": ["cs_old"]})
        assert received == ["series_loading"]
        assert len(server.connections) == 2
        await second.close()
