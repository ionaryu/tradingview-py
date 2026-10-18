from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import gzip
import json
import secrets
import socket

import pytest

from tradingview._types import AbortController
from tradingview.client import TradingViewClient, create_proxy, createProxy
from tradingview.errors import TradingViewError
from tradingview.http.request import request


@asynccontextmanager
async def loopback_proxy_fixture():
    auth_secret = f"user:{secrets.token_hex(8)}"
    expected_auth = "Basic " + base64.b64encode(auth_secret.encode("utf-8")).decode("ascii")
    connects: list[dict] = []

    # 1. Start a local target server supporting both plain HTTP and WebSocket upgrade
    async def target_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            req_line = await reader.readline()
            if not req_line:
                writer.close()
                return
            parts = req_line.decode("latin1").strip().split(" ")
            method, path = parts[0], parts[1]
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
                k, v = line.decode("latin1").rstrip("\r\n").split(":", 1)
                headers[k.strip().lower()] = v.strip()

            body_len = int(headers.get("content-length", "0"))
            body = (await reader.readexactly(body_len)).decode("utf-8", errors="replace") if body_len > 0 else ""

            if headers.get("upgrade", "").lower() == "websocket":
                import hashlib

                ws_key = headers["sec-websocket-key"]
                accept = base64.b64encode(
                    hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
                ).decode("ascii")
                resp = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                )
                writer.write(resp.encode("latin1"))
                await writer.drain()
                # Read one masked client text frame
                hdr = await reader.readexactly(2)
                length = hdr[1] & 0x7F
                mask = await reader.readexactly(4)
                masked = await reader.readexactly(length)
                unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(masked)).decode("utf-8")
                reply = json.dumps(
                    {
                        "host": headers.get("host", ""),
                        "origin": headers.get("origin", ""),
                        "echo": unmasked,
                    }
                ).encode("utf-8")
                frame = bytearray([0x81, len(reply)]) + reply
                writer.write(bytes(frame))
                await writer.drain()
                return

            if path == "/redirect":
                resp = (
                    "HTTP/1.1 302 Found\r\n"
                    "Location: /echo?redirected=1\r\n"
                    "Set-Cookie: a=1; Path=/\r\n"
                    "Set-Cookie: b=2; Path=/\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                )
                writer.write(resp.encode("latin1"))
                await writer.drain()
                return

            if path == "/gzip":
                gz_body = gzip.compress(json.dumps({"path": "/gzip"}).encode("utf-8"))
                resp_hdr = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Encoding: gzip\r\n"
                    f"Content-Length: {len(gz_body)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("latin1")
                writer.write(resp_hdr + gz_body)
                await writer.drain()
                return

            payload = json.dumps(
                {
                    "method": method,
                    "host": headers.get("host", ""),
                    "path": path,
                    "cookie": headers.get("cookie", ""),
                    "contentType": headers.get("content-type", ""),
                    "body": body,
                }
            ).encode("utf-8")
            resp_hdr = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("latin1")
            writer.write(resp_hdr + payload)
            await writer.drain()
        finally:
            writer.close()

    target_srv = await asyncio.start_server(target_handler, "127.0.0.1", 0)
    plain_port = target_srv.sockets[0].getsockname()[1]

    # 2. Start HTTP CONNECT proxy server that forwards tunnels to target_srv
    async def proxy_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            req_line = await reader.readline()
            if not req_line:
                writer.close()
                return
            parts = req_line.decode("latin1").strip().split(" ")
            target = parts[1] if len(parts) > 1 else ""
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
                if b":" in line:
                    k, v = line.decode("latin1").rstrip("\r\n").split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            authorized = headers.get("proxy-authorization") == expected_auth
            connects.append({"target": target, "authorized": authorized})
            if not authorized:
                writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return

            t_reader, t_writer = await asyncio.open_connection("127.0.0.1", plain_port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter):
                try:
                    while True:
                        chunk = await r.read(4096)
                        if not chunk:
                            break
                        w.write(chunk)
                        await w.drain()
                except Exception:
                    pass
                finally:
                    try:
                        w.close()
                    except Exception:
                        pass

            await asyncio.gather(pipe(reader, t_writer), pipe(t_reader, writer))
        finally:
            writer.close()

    proxy_srv = await asyncio.start_server(proxy_handler, "127.0.0.1", 0)
    proxy_port = proxy_srv.sockets[0].getsockname()[1]

    def make_proxy_url(auth: str = auth_secret, protocol: str = "http") -> str:
        return f"{protocol}://{auth}@127.0.0.1:{proxy_port}"

    try:
        yield {"proxy_url": make_proxy_url, "plain_port": plain_port, "connects": connects}
    finally:
        proxy_srv.close()
        target_srv.close()
        await proxy_srv.wait_closed()
        await target_srv.wait_closed()


class TestCreateProxy:
    async def test_tunnels_library_http_requests_with_proxy_basic_auth(self):
        async with loopback_proxy_fixture() as fix:
            proxy = createProxy(fix["proxy_url"]())
            response = await request(
                "http://api.tradingview.test:8080/echo",
                {"form": {"symbol": "BINANCE:BTCUSDT"}, "credentials": {"session": "abc", "signature": "def"}},
                {"fetch": proxy.fetch},
            )
            assert response.status == 200
            assert response.data == {
                "method": "POST",
                "host": "api.tradingview.test:8080",
                "path": "/echo",
                "cookie": "sessionid=abc;sessionid_sign=def",
                "contentType": "application/x-www-form-urlencoded",
                "body": "symbol=BINANCE%3ABTCUSDT",
            }
            assert {"target": "api.tradingview.test:8080", "authorized": True} in fix["connects"]

    async def test_follows_or_exposes_redirects_keeps_set_cookies_and_decodes_gzip(self):
        async with loopback_proxy_fixture() as fix:
            proxy = create_proxy(fix["proxy_url"]())
            manual = await proxy.fetch("http://api.tradingview.test:8080/redirect", {"redirect": "manual"})
            assert manual.status == 302
            assert manual.headers.get("location") == "/echo?redirected=1"
            assert manual.headers.getSetCookie() == ["a=1; Path=/", "b=2; Path=/"]

            followed = await proxy.fetch(
                "http://api.tradingview.test:8080/redirect", {"method": "POST", "body": "x"}
            )
            assert followed.redirected is True
            assert followed.url == "http://api.tradingview.test:8080/echo?redirected=1"
            data = await followed.json()
            assert data["method"] == "GET"
            assert data["path"] == "/echo?redirected=1"
            assert data["body"] == ""

            gz = await proxy.fetch("http://api.tradingview.test:8080/gzip")
            assert (await gz.json())["path"] == "/gzip"

    async def test_tunnels_websocket_transport_with_origin_header(self):
        async with loopback_proxy_fixture() as fix:
            proxy = create_proxy(fix["proxy_url"]())
            loop = asyncio.get_running_loop()
            opened = loop.create_future()
            message = loop.create_future()
            transport = proxy.transport(
                {"url": "ws://data.tradingview.test:8080/", "origin": "https://www.tradingview.com", "headers": {}},
                {
                    "onOpen": lambda: opened.set_result(True) if not opened.done() else None,
                    "onMessage": lambda d: message.set_result(d) if not message.done() else None,
                    "onClose": lambda *_a: None,
                    "onError": lambda err: opened.set_exception(err) if not opened.done() else None,
                },
            )
            try:
                await opened
                transport.send("through the proxy")
                raw = await message
                assert json.loads(raw) == {
                    "host": "data.tradingview.test:8080",
                    "origin": "https://www.tradingview.com",
                    "echo": "through the proxy",
                }
                assert {"target": "data.tradingview.test:8080", "authorized": True} in fix["connects"]
            finally:
                transport.close()

    async def test_reports_refused_tunnel_on_both_paths_without_leaking_credentials(self):
        async with loopback_proxy_fixture() as fix:
            wrong = "user:wrong-secret-value"
            proxy = create_proxy(fix["proxy_url"](wrong))

            with pytest.raises(TradingViewError) as http_exc:
                await request("http://api.tradingview.test:8080/echo", {}, {"fetch": proxy.fetch})
            assert "HTTP 407" in http_exc.value.message
            assert "wrong-secret-value" not in http_exc.value.message

            client = TradingViewClient(
                {
                    "authToken": "token",
                    "transport": lambda req, handlers: proxy.transport(
                        {**req, "url": "ws://data.tradingview.test:8080/"}, handlers
                    ),
                }
            )
            with pytest.raises(TradingViewError) as ws_exc:
                await client.ready
            assert ws_exc.value.code == "CONNECTION_ERROR"
            assert "HTTP 407" in ws_exc.value.message
            assert "wrong-secret-value" not in ws_exc.value.message
            await client.close()
            assert {"target": "data.tradingview.test:8080", "authorized": False} in fix["connects"]

    async def test_honours_abort_signal(self):
        async with loopback_proxy_fixture() as fix:
            proxy = create_proxy(fix["proxy_url"]())
            controller = AbortController()
            controller.abort()
            with pytest.raises(Exception) as exc_info:
                await proxy.fetch("http://api.tradingview.test:8080/echo", {"signal": controller.signal})
            assert getattr(exc_info.value, "name", "") == "AbortError"

    async def test_uses_caller_supplied_agent_for_both_paths(self):
        async with loopback_proxy_fixture() as fix:
            hosts: list[str] = []

            class RoutingAgent:
                def createConnection(self, options: dict) -> socket.socket:
                    hosts.append(f"{options['host']}:{options['port']}")
                    return socket.create_connection(("127.0.0.1", fix["plain_port"]))

            proxy = create_proxy(RoutingAgent())
            resp = await proxy.fetch("http://api.tradingview.test:8080/echo")
            assert (await resp.json())["host"] == "api.tradingview.test:8080"

            loop = asyncio.get_running_loop()
            opened = loop.create_future()
            transport = proxy.transport(
                {"url": "ws://data.tradingview.test:8080/", "origin": "https://www.tradingview.com", "headers": {}},
                {
                    "onOpen": lambda: opened.set_result(True) if not opened.done() else None,
                    "onMessage": lambda _d: None,
                    "onClose": lambda *_a: None,
                    "onError": lambda e: opened.set_exception(e) if not opened.done() else None,
                },
            )
            await opened
            transport.close()
            assert hosts == ["api.tradingview.test:8080", "data.tradingview.test:8080"]

    async def test_reports_unreachable_or_stalled_proxy(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            closed_port = s.getsockname()[1]

        with pytest.raises(TradingViewError, match="is unreachable"):
            await create_proxy(f"http://u:hidden@127.0.0.1:{closed_port}").fetch("http://api.tradingview.test/")

        held_writers: list[asyncio.StreamWriter] = []

        async def stalled_handler(_r: asyncio.StreamReader, w: asyncio.StreamWriter):
            held_writers.append(w)
            await asyncio.sleep(5)

        stalled_srv = await asyncio.start_server(stalled_handler, "127.0.0.1", 0)
        stalled_port = stalled_srv.sockets[0].getsockname()[1]
        try:
            proxy = create_proxy(f"http://127.0.0.1:{stalled_port}", {"connectTimeoutMs": 60})
            with pytest.raises(TradingViewError) as exc_info:
                await proxy.fetch("http://api.tradingview.test/")
            assert exc_info.value.code == "TIMEOUT"
        finally:
            for w in held_writers:
                w.close()
            stalled_srv.close()
            await stalled_srv.wait_closed()

    def test_rejects_unsupported_proxy_urls(self):
        with pytest.raises(TradingViewError, match="pass an Agent"):
            create_proxy("socks5://127.0.0.1:1080")
        with pytest.raises(TradingViewError, match="Invalid proxy URL"):
            create_proxy("not a url")
