from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlparse

import websockets
from websockets.exceptions import ConnectionClosed

from .._types import AttrDict

TransportHandlers = dict[str, Callable[..., Any]] | Any
TransportRequest = dict[str, Any] | AttrDict


class Transport(Protocol):
    @property
    def is_open(self) -> bool: ...

    @property
    def isOpen(self) -> bool: ...

    def send(self, data: str) -> None: ...

    def close(self) -> None: ...

    def terminate(self) -> None: ...


TransportFactory = Callable[[Any, Any], Any]
WsTransportOptions = dict[str, Any]
HttpAgentLike = Any


def _call_handler(handlers: Any, name: str, *args: Any) -> None:
    fn = handlers.get(name) if isinstance(handlers, dict) else getattr(handlers, name, None)
    if callable(fn):
        fn(*args)


class _AsyncioWsTransport:
    """Bridges synchronous `Transport` interface (`send`, `close`, `terminate`, `isOpen`)
    to an `asyncio` background task running `websockets.connect`.
    """

    def __init__(
        self,
        request: dict[str, Any] | Any,
        handlers: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._request = AttrDict(request) if isinstance(request, dict) else request
        self._handlers = handlers
        self._extra = dict(extra or {})
        self._is_open = False
        self._closing = False
        self._terminated = False
        self._closed = False
        self._ws: Any = None
        self._send_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
        except RuntimeError:
            pass

    @property
    def is_open(self) -> bool:
        return self._is_open and not self._closed and not self._closing

    @property
    def isOpen(self) -> bool:
        return self.is_open

    def send(self, data: str) -> None:
        if self._closed or self._closing:
            return
        self._send_queue.put_nowait(data)

    def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        self._is_open = False
        self._send_queue.put_nowait(None)
        if self._ws is None and self._task is not None and not self._task.done():
            self._task.cancel()
        elif self._ws is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._graceful_close())
            except RuntimeError:
                pass

    def terminate(self) -> None:
        if self._closed:
            return
        self._terminated = True
        self._closing = True
        self._is_open = False
        self._send_queue.put_nowait(None)
        if self._ws is not None and hasattr(self._ws, "transport") and self._ws.transport is not None:
            self._ws.transport.abort()
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _graceful_close(self) -> None:
        try:
            if self._ws is not None:
                await asyncio.wait_for(self._ws.close(1000, ""), timeout=1.5)
        except Exception:
            if self._ws is not None and hasattr(self._ws, "transport") and self._ws.transport is not None:
                self._ws.transport.abort()

    async def _writer(self) -> None:
        while True:
            msg = await self._send_queue.get()
            if msg is None or self._ws is None:
                break
            try:
                await self._ws.send(msg)
            except Exception:
                break

    async def _run(self) -> None:
        url = str(self._request["url"])
        origin = str(self._request.get("origin") or "https://www.tradingview.com")
        raw_headers = dict(self._request.get("headers") or {})
        additional_headers = {k: v for k, v in raw_headers.items() if k.lower() != "origin"}

        connect_kwargs: dict[str, Any] = {
            "origin": origin,
            "additional_headers": additional_headers,
            "max_size": None,
            "ping_interval": None,
            "close_timeout": 1.0,
        }
        user_agent = raw_headers.get("User-Agent") or raw_headers.get("user-agent")
        if user_agent:
            connect_kwargs["user_agent_header"] = user_agent
            additional_headers.pop("User-Agent", None)
            additional_headers.pop("user-agent", None)

        socket_factory = self._extra.get("socket_factory")
        ssl_ctx = self._extra.get("ssl")
        parsed = urlparse(url)

        close_code = 1006
        close_reason = ""

        try:
            if callable(socket_factory):
                sock = await socket_factory(url)
                connect_kwargs["sock"] = sock
                if parsed.scheme == "wss":
                    connect_kwargs["ssl"] = ssl_ctx if ssl_ctx is not None else True
                    connect_kwargs["server_hostname"] = parsed.hostname
            elif parsed.scheme == "wss" and ssl_ctx is not None:
                connect_kwargs["ssl"] = ssl_ctx

            async with websockets.connect(url, **connect_kwargs) as ws:
                self._ws = ws
                if self._closing:
                    close_code = 1006 if self._terminated else 1000
                    return
                self._is_open = True
                _call_handler(self._handlers, "onOpen")
                self._writer_task = asyncio.create_task(self._writer())
                try:
                    async for message in ws:
                        text = message.decode("utf-8", errors="replace") if isinstance(message, bytes) else str(message)
                        _call_handler(self._handlers, "onMessage", text)
                    close_code = 1006 if self._terminated else (ws.close_code if ws.close_code is not None else 1000)
                    close_reason = ws.close_reason or ""
                except ConnectionClosed as cc:
                    close_code = 1006 if self._terminated else (cc.rcvd.code if cc.rcvd else 1006)
                    close_reason = cc.rcvd.reason if cc.rcvd else ""
                finally:
                    self._is_open = False
                    if self._writer_task and not self._writer_task.done():
                        self._writer_task.cancel()
        except asyncio.CancelledError:
            self._is_open = False
            close_code = 1006 if (self._terminated or not self._closing) else 1000
        except Exception as exc:
            self._is_open = False
            if not self._closing:
                _call_handler(self._handlers, "onError", exc)
            close_code = 1006
        finally:
            self._is_open = False
            self._closed = True
            _call_handler(self._handlers, "onClose", close_code, close_reason)


def ws_transport_with(extra_fn: Callable[[str], dict[str, Any]]) -> TransportFactory:
    def factory(request: dict[str, Any] | Any, handlers: Any) -> _AsyncioWsTransport:
        url = request["url"] if isinstance(request, dict) else getattr(request, "url", "")
        return _AsyncioWsTransport(request, handlers, extra_fn(str(url)))

    return factory


wsTransportWith = ws_transport_with


def create_ws_transport(options: dict[str, Any] | None = None, **kwargs: Any) -> TransportFactory:
    """Creates a transport based on the `websockets` package."""
    opts = {**(options or {}), **kwargs}

    def _extra(url: str) -> dict[str, Any]:
        agent = opts.get("agent")
        if callable(agent):
            agent = agent(url)
        if agent is not None:
            if hasattr(agent, "create_socket") and callable(agent.create_socket):
                return {"socket_factory": agent.create_socket, "ssl": getattr(agent, "ssl_context", None)}
            if hasattr(agent, "createConnection") and callable(agent.createConnection):
                return {"socket_factory": agent.createConnection, "ssl": getattr(agent, "ssl_context", None)}
        return {k: v for k, v in opts.items() if k != "agent"}

    return ws_transport_with(_extra)


createWsTransport = create_ws_transport

ws_transport: TransportFactory = ws_transport_with(lambda _url: {})
wsTransport: TransportFactory = ws_transport
