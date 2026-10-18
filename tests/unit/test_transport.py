from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import time

import pytest
import websockets

from tradingview.client import TradingViewClient, ws_transport
from tradingview.errors import TradingViewError
from tradingview.protocol import encode_frame


@asynccontextmanager
async def local_ws_server(mode: str):
    async def handler(ws):
        if mode == "echo":
            req_headers = ws.request.headers if ws.request else {}
            origin = req_headers.get("Origin") or req_headers.get("origin") or ""
            x_test = req_headers.get("X-Test") or req_headers.get("x-test") or ""
            msg = await ws.recv()
            payload = json.dumps({"origin": origin, "header": x_test, "echo": msg}).encode("utf-8")
            await ws.send(payload)
            await ws.close(1000, "finished")
        elif mode == "drop":
            await ws.send(encode_frame({"session_id": "native", "protocol": "json"}))
            await ws.recv()  # set_auth_token
            await ws.recv()  # ping_server
            ws.transport.abort()
        elif mode == "silent":
            await ws.send(encode_frame({"session_id": "native", "protocol": "json"}))
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

    def process_request(connection, request):
        if mode == "reject":
            return connection.respond(403, "Forbidden\n")
        return None

    server = await websockets.serve(handler, "127.0.0.1", 0, process_request=process_request)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


class TestNativeWebSocketTransport:
    async def test_sends_headers_and_text_decodes_binary_and_reports_remote_close(self):
        async with local_ws_server("echo") as url:
            loop = asyncio.get_running_loop()
            opened = loop.create_future()
            message = loop.create_future()
            closed = loop.create_future()
            errors: list[Exception] = []

            transport = ws_transport(
                {"url": url, "origin": "https://www.tradingview.com", "headers": {"X-Test": "native"}},
                {
                    "onOpen": lambda: opened.set_result(True) if not opened.done() else None,
                    "onMessage": lambda data: message.set_result(data) if not message.done() else None,
                    "onError": lambda err: errors.append(err),
                    "onClose": lambda code, reason: closed.set_result({"code": code, "reason": reason})
                    if not closed.done()
                    else None,
                },
            )
            try:
                await opened
                assert transport.isOpen is True
                transport.send("Unicode: 日本語")
                assert json.loads(await message) == {
                    "origin": "https://www.tradingview.com",
                    "header": "native",
                    "echo": "Unicode: 日本語",
                }
                assert await closed == {"code": 1000, "reason": "finished"}
                assert transport.isOpen is False
                transport.close()
                assert errors == []
            finally:
                transport.close()

    async def test_propagates_failed_native_handshake_to_client_readiness_and_sessions(self):
        async with local_ws_server("reject") as url:
            client = TradingViewClient(
                {"transport": lambda req, handlers: ws_transport({**req, "url": url}, handlers)}
            )
            errors: list[str] = []
            client.on("error", lambda err: errors.append(err.code))
            closed = asyncio.get_running_loop().create_future()
            client.on("close", lambda *_a: closed.set_result(True) if not closed.done() else None)
            cause_holder: list = []
            client.registerSession("test", {"onPacket": lambda _p: None, "onClose": lambda err, _e: cause_holder.append(err.cause)})
            try:
                with pytest.raises(TradingViewError) as exc_info:
                    await client.ready
                assert exc_info.value.code == "CONNECTION_ERROR"
                await closed
                assert client.isClosed is True
                assert errors == ["CONNECTION_ERROR"]
                assert cause_holder[0].code == "CONNECTION_ERROR"
            finally:
                await client.close()


class TestNativeWebSocketLoss:
    @staticmethod
    def _connect(url: str, options: dict | None = None):
        socket_closes: list[int | None] = []
        loop = asyncio.get_running_loop()

        def custom_transport(req, handlers):
            orig_close = handlers["onClose"]

            def wrapped_close(code=None, reason=""):
                socket_closes.append(code)
                orig_close(code, reason)

            return ws_transport({**req, "url": url}, {**handlers, "onClose": wrapped_close})

        client = TradingViewClient({**(options or {}), "transport": custom_transport})
        errors: list[str] = []
        client.on("error", lambda err: errors.append(err.code))
        sessions: list[tuple[str, bool]] = []
        client.registerSession(
            "cs_native",
            {"onPacket": lambda _p: None, "onClose": lambda err, expected: sessions.append((err.code, expected))},
        )
        closed = loop.create_future()
        client.on("close", lambda code=None, _r=None: closed.set_result(code) if not closed.done() else None)
        return client, errors, sessions, closed, socket_closes

    async def test_reports_abrupt_socket_loss_to_sessions_as_unexpected_disconnection(self):
        async with local_ws_server("drop") as url:
            client, errors, sessions, closed, _ = self._connect(url)
            try:
                await client.ready
                client.send("ping_server")
                assert await closed == 1006
                assert client.isClosed is True
                assert sessions == [("DISCONNECTED", False)]
                assert errors == []
                with pytest.raises(TradingViewError, match="closed"):
                    client.send("late")
            finally:
                await client.close()

    async def test_detects_silent_peer_and_releases_socket_at_once(self):
        async with local_ws_server("silent") as url:
            client, errors, sessions, closed, socket_closes = self._connect(url, {"inactivityTimeoutMs": 100})
            try:
                await client.ready
                start = time.monotonic()
                assert await closed == 1006
                assert (time.monotonic() - start) < 1.0
                assert errors == ["CONNECTION_ERROR"]
                assert sessions == [("DISCONNECTED", False)]
                assert socket_closes == [1006]
            finally:
                await client.close()

    async def test_close_releases_socket_of_peer_that_never_answers_close(self):
        async with local_ws_server("silent") as url:
            client, _, sessions, _, socket_closes = self._connect(url, {"inactivityTimeoutMs": 0})
            await client.ready
            await client.close()
            assert client.isClosed is True
            assert sessions == [("DISCONNECTED", True)]
            deadline = time.monotonic() + 1.0
            while not socket_closes and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert len(socket_closes) == 1
