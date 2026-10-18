from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import math
import time
from typing import Any

from .._types import AbortController, AttrDict
from ..errors import TradingViewError, to_trading_view_error
from ..events import Emitter
from ..http.account import get_user
from ..http.request import Credentials, DEFAULT_USER_AGENT
from ..protocol.framing import ServerHello, ServerPacket, decode_frames, encode_heartbeat, encode_packet
from .transport import Transport, TransportFactory, ws_transport

ServerName = str
DebugOption = bool | Callable[..., Any]
ClientOptions = dict[str, Any]
ClientEvents = dict[str, Any]


class SessionHandler:
    """Interface implemented by chart, replay, and quote sessions."""

    def on_packet(self, packet: ServerPacket) -> None:
        pass

    onPacket = on_packet

    def on_close(self, error: TradingViewError, expected: bool) -> None:
        pass

    onClose = on_close


def _call_session_packet(session: Any, packet: ServerPacket) -> None:
    if isinstance(session, dict):
        fn = session.get("onPacket") or session.get("on_packet")
        if callable(fn):
            fn(packet)
    else:
        fn = getattr(session, "onPacket", None) or getattr(session, "on_packet", None)
        if callable(fn):
            fn(packet)


def _call_session_close(session: Any, error: TradingViewError, expected: bool) -> None:
    if isinstance(session, dict):
        fn = session.get("onClose") or session.get("on_close")
        if callable(fn):
            fn(error, expected)
    else:
        fn = getattr(session, "onClose", None) or getattr(session, "on_close", None)
        if callable(fn):
            fn(error, expected)


class TradingViewClient(Emitter):
    """One websocket connection to TradingView. Chart and quote sessions are multiplexed over it."""

    def __init__(self, options: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__()
        opts = {**(options or {}), **kwargs}

        debug_opt = opts.get("debug")
        if debug_opt is True:
            self._log: Callable[..., Any] | None = lambda *args: print("[tradingview]", *args)
        elif callable(debug_opt):
            self._log = debug_opt
        else:
            self._log = None

        self._sessions: dict[str, Any] = {}
        self._queue: list[str] = []
        self._authenticated = False
        self._auth_token: str | None = None
        self._auth_controller = AbortController()
        self._closed = False
        self._closing = False
        self._close_requested = False
        self._failure: TradingViewError | None = None
        self._hello: ServerHello | None = None
        self._close_waiters: list[asyncio.Future[None]] = []
        self._last_activity: float = 0.0

        loop = asyncio.get_event_loop()
        self.ready: asyncio.Future[None] = loop.create_future()
        # Prevent "Future exception was never retrieved" warning when not awaited
        self.ready.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)

        inactivity_raw = opts.get("inactivityTimeoutMs", opts.get("inactivity_timeout_ms", 60_000))
        self._inactivity_timeout = float(inactivity_raw) if inactivity_raw is not None else 60_000.0
        self._inactivity_handle: asyncio.TimerHandle | None = None

        connect_timeout_ms = float(opts.get("connectTimeoutMs", opts.get("connect_timeout_ms", 20_000)))
        self._ready_handle: asyncio.TimerHandle | None = loop.call_later(
            connect_timeout_ms / 1000.0,
            lambda: self._fail(TradingViewError("TIMEOUT", f"Connection not ready after {int(connect_timeout_ms)} ms")),
        )

        server = opts.get("server") or "data"
        factory: TransportFactory = opts.get("transport") or ws_transport
        extra_headers = dict(opts.get("headers") or {})
        self._transport: Any = factory(
            AttrDict(
                {
                    "url": f"wss://{server}.tradingview.com/socket.io/websocket?from=chart&type=chart",
                    "origin": "https://www.tradingview.com",
                    "headers": {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Accept-Language": "en-US,en;q=0.9",
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache",
                        **extra_headers,
                    },
                }
            ),
            AttrDict(
                {
                    "onOpen": self._on_open,
                    "onMessage": self._on_message,
                    "onClose": self._on_close,
                    "onError": self._on_transport_error,
                }
            ),
        )

        auth_token = opts.get("authToken") or opts.get("auth_token")
        credentials = opts.get("credentials")
        if auth_token:
            self._auth_token = str(auth_token)
        elif credentials and (
            (isinstance(credentials, dict) and credentials.get("session"))
            or getattr(credentials, "session", None)
        ):
            loop.create_task(
                self._lookup_credentials(
                    credentials,
                    location=opts.get("location"),
                    fetch=opts.get("fetch"),
                )
            )
        else:
            self._auth_token = "unauthorized_user_token"

    async def _lookup_credentials(
        self,
        credentials: dict[str, Any],
        location: str | None = None,
        fetch: Any = None,
    ) -> None:
        try:
            user = await get_user(
                credentials,
                {"location": location, "fetch": fetch, "signal": self._auth_controller.signal},
            )
            if self._closed or self._closing:
                return
            self._auth_token = user.authToken
            self._authenticate()
        except Exception as error:
            if self._closed or self._closing:
                return
            tv_err = to_trading_view_error(error)
            self._fail(TradingViewError("AUTH_ERROR", f"Credentials error: {tv_err.message}", {"cause": error}))

    def _on_transport_error(self, error: Exception) -> None:
        if self._closing:
            return
        msg = getattr(error, "message", None) or str(error)
        self._fail(TradingViewError("CONNECTION_ERROR", f"WebSocket error: {msg}", {"cause": error}))

    @property
    def is_open(self) -> bool:
        t_open = getattr(self._transport, "isOpen", getattr(self._transport, "is_open", False))
        return not self._closed and bool(t_open)

    isOpen = is_open

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    isAuthenticated = is_authenticated

    @property
    def is_closed(self) -> bool:
        return self._closed

    isClosed = is_closed

    @property
    def server_info(self) -> ServerHello | None:
        return self._hello

    serverInfo = server_info

    def create_chart(self) -> Any:
        from ..chart.chart_session import ChartSession

        return ChartSession(self)

    createChart = create_chart

    def create_quote_session(self, options: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        from ..quote.quote_session import QuoteSession

        return QuoteSession(self, {**(options or {}), **kwargs})

    createQuoteSession = create_quote_session

    def send(self, method: str, params: Sequence[Any] = ()) -> None:
        """Sends a raw packet. Packets are queued until the connection is ready."""
        if self._closed:
            raise TradingViewError("INVALID_STATE", f"Cannot send '{method}': the client is closed")
        self._queue.append(encode_packet(method, params))
        self._flush()

    def register_session(self, session_id: str, handler: Any) -> None:
        self._sessions[session_id] = handler

    registerSession = register_session

    def unregister_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    unregisterSession = unregister_session

    def log(self, *args: Any) -> None:
        if self._log is not None:
            self._log(*args)

    async def close(self) -> None:
        """Closes the connection. Resolves once the websocket is closed. Idempotent."""
        if self._closed:
            return
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._close_waiters.append(waiter)
        self._close_requested = True
        if not self._closing:
            self._closing = True
            self._auth_controller.abort()
            loop.call_later(0.3, lambda: self._force_close(1000, "Close timeout"))
            self._transport.close()
        await waiter

    def _on_open(self) -> None:
        if self._log is not None:
            self._log("open")
        self._emit("open")
        self._last_activity = time.monotonic() * 1000.0
        self._watch_inactivity(self._inactivity_timeout)
        self._authenticate()

    def _watch_inactivity(self, delay_ms: float) -> None:
        if not (self._inactivity_timeout > 0 and math.isfinite(self._inactivity_timeout)) or self._closed:
            return
        capped_ms = min(delay_ms, float(2**31 - 1))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _check() -> None:
            if self._closed:
                return
            idle_ms = (time.monotonic() * 1000.0) - self._last_activity
            if idle_ms < self._inactivity_timeout:
                self._watch_inactivity(self._inactivity_timeout - idle_ms)
                return
            self._fail(
                TradingViewError("CONNECTION_ERROR", f"No data from the server for {int(idle_ms)} ms"),
                unresponsive=True,
            )

        self._inactivity_handle = loop.call_later(capped_ms / 1000.0, _check)

    def _authenticate(self) -> None:
        t_open = getattr(self._transport, "isOpen", getattr(self._transport, "is_open", False))
        if self._authenticated or not self._auth_token or not t_open or self._closing:
            return
        self._transport.send(encode_packet("set_auth_token", [self._auth_token]))
        self._authenticated = True
        if self._ready_handle is not None:
            self._ready_handle.cancel()
            self._ready_handle = None
        if not self.ready.done():
            self.ready.set_result(None)
        self._emit("ready")
        self._flush()

    def _flush(self) -> None:
        while self._authenticated and self.is_open and self._queue:
            packet = self._queue.pop(0)
            if self._log is not None:
                self._log("send", packet)
            self._transport.send(packet)

    def _on_message(self, data: str) -> None:
        if self._closed:
            return
        self._last_activity = time.monotonic() * 1000.0
        for frame in decode_frames(data):
            ftype = frame["type"]
            if ftype == "heartbeat":
                if self.is_open:
                    self._transport.send(encode_heartbeat(frame["id"]))
                self._emit("heartbeat", frame["id"])
                continue
            if ftype == "invalid":
                if self._log is not None:
                    self._log("invalid frame", frame["raw"])
                continue
            if ftype == "data":
                if self._log is not None:
                    self._log("data", frame["data"])
                hello = frame["data"]
                if isinstance(hello, dict) and "session_id" in hello:
                    self._hello = AttrDict(hello)
                    self._emit("hello", self._hello)
                continue

            packet = AttrDict(frame["packet"])
            if self._log is not None:
                self._log("packet", packet)
            if packet["m"] == "protocol_error":
                p_list = packet.get("p") or []
                first_arg = p_list[0] if p_list else ""
                self._emit(
                    "error",
                    TradingViewError(
                        "PROTOCOL_ERROR",
                        f"Protocol error: {first_arg}",
                        {"details": p_list},
                    ),
                )
                self._transport.close()
                continue

            p_list = packet.get("p") or []
            session_id = p_list[0] if p_list else None
            session = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if session is not None:
                _call_session_packet(session, packet)
            else:
                self._emit("packet", packet)

    def _fail(self, error: TradingViewError, unresponsive: bool = False) -> None:
        if self._closed:
            return
        if self._ready_handle is not None:
            self._ready_handle.cancel()
            self._ready_handle = None
        was_ready = self._authenticated
        if self._failure is None:
            self._failure = error
        if not self.ready.done():
            self.ready.set_exception(error)
        if was_ready or self._has_listeners("error"):
            self._emit("error", error)
        if not was_ready or error.code in ("AUTH_ERROR", "CONNECTION_ERROR"):
            self._closing = True
            self._auth_controller.abort()
            term_fn = getattr(self._transport, "terminate", None)
            if unresponsive and callable(term_fn):
                term_fn()
            else:
                self._transport.close()
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(0.3, lambda: self._force_close(None, error.message))
            except RuntimeError:
                pass

    def _force_close(self, code: int | None = None, reason: str | None = None) -> None:
        if self._closed:
            return
        term_fn = getattr(self._transport, "terminate", None)
        if callable(term_fn):
            term_fn()
        self._on_close(code, reason)

    def _on_close(self, code: int | None = None, reason: str | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._auth_controller.abort()
        self._authenticated = False
        if self._ready_handle is not None:
            self._ready_handle.cancel()
            self._ready_handle = None
        if self._inactivity_handle is not None:
            self._inactivity_handle.cancel()
            self._inactivity_handle = None
        if self._log is not None:
            self._log("close", code, reason)

        cause = self._failure
        why = (cause.message if cause is not None else None) or reason
        error = TradingViewError(
            "DISCONNECTED",
            f"Connection closed{f': {why}' if why else ''}",
            {"details": {"code": code, "reason": reason}, "cause": cause},
        )
        if not self.ready.done():
            self.ready.set_exception(error)
        for session in list(self._sessions.values()):
            _call_session_close(session, error, self._close_requested)
        self._sessions.clear()
        self._queue.clear()

        self._emit("close", code, reason)
        waiters = list(self._close_waiters)
        self._close_waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)
