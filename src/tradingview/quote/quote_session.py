from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import json
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from ..events import Emitter
from ..protocol.ids import create_session_id
from .fields import QuoteData, QuoteField, QuoteFieldPreset, resolve_quote_fields

QuoteSessionOptions = dict[str, Any]
QuoteSubscriptionOptions = dict[str, Any]
QuoteSubscriptionEvents = dict[str, Any]
QuoteSessionEvents = dict[str, Any]


def quote_symbol_key(symbol: str, session: str = "regular") -> str:
    """Key identifying a symbol + session in quote packets."""
    return "=" + json.dumps({"session": session, "symbol": symbol}, separators=(",", ":"))


quoteSymbolKey = quote_symbol_key


class QuoteSubscription(Emitter):
    """Live quotes for one symbol. Create it with `quote_session.subscribe()`."""

    def __init__(self, symbol: str, session: str, on_close: Callable[[QuoteSubscription], None]) -> None:
        super().__init__()
        self.symbol: str = symbol
        self.session: str = session
        self.key: str = quote_symbol_key(symbol, session)
        self._on_close = on_close
        self._data: AttrDict = AttrDict()
        self._loaded: bool = False
        self._closed: bool = False

    @property
    def data(self) -> QuoteData:
        return AttrDict(self._data)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    isLoaded = is_loaded

    @property
    def is_closed(self) -> bool:
        return self._closed

    isClosed = is_closed

    def close(self) -> None:
        """Stops receiving quotes for this subscription. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._on_close(self)

    def seed(self, source: QuoteSubscription) -> None:
        if not source.is_loaded:
            return

        def _do_seed() -> None:
            if self._closed or self._loaded:
                return
            self._data = source.data
            self._loaded = True
            self._emit("data", self.data, self.data)
            self._emit("loaded")

        try:
            loop = asyncio.get_running_loop()
            loop.call_soon(_do_seed)
        except RuntimeError:
            _do_seed()

    def handle_packet(self, packet: dict[str, Any]) -> None:
        if self._closed:
            return
        if packet.get("m") == "quote_completed":
            self._loaded = True
            self._emit("loaded")
            return
        p_list = packet.get("p") or []
        payload = p_list[1] if len(p_list) > 1 and isinstance(p_list[1], dict) else {}
        status = payload.get("s")
        if status == "ok":
            changes = AttrDict(payload.get("v") or {})
            self._data.update(changes)
            self._emit("data", self.data, changes)
        elif status == "error":
            errmsg = payload.get("errmsg") or "unknown"
            self._emit(
                "error",
                TradingViewError(
                    "QUOTE_ERROR",
                    f"Quote error ({self.symbol}): {errmsg}",
                    {"details": p_list},
                ),
            )

    handlePacket = handle_packet

    def handle_close(self, error: TradingViewError, expected: bool) -> None:
        if self._closed:
            return
        self._closed = True
        if not expected:
            self._emit("error", error)

    handleClose = handle_close


class QuoteSession(Emitter):
    """A set of live quote subscriptions sharing the same fields."""

    def __init__(self, client: Any, options: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__()
        opts = {**(options or {}), **kwargs}
        self.id: str = create_session_id("qs")
        self.client = client
        self._subscriptions: dict[str, list[QuoteSubscription]] = {}
        self._fields: list[str] = resolve_quote_fields(opts.get("fields"))
        self._deleted: bool = False

        client.register_session(
            self.id,
            {
                "onPacket": self._on_packet,
                "onClose": self._on_client_close,
            },
        )
        client.send("quote_create_session", [self.id])
        client.send("quote_set_fields", [self.id, *self._fields])

    @property
    def fields(self) -> list[str]:
        return list(self._fields)

    @property
    def is_deleted(self) -> bool:
        return self._deleted

    isDeleted = is_deleted

    def set_fields(self, fields: str | Sequence[str]) -> None:
        """Changes the requested fields for every subscription."""
        self._assert_alive()
        self._fields = resolve_quote_fields(fields)
        self.client.send("quote_set_fields", [self.id, *self._fields])

    setFields = set_fields

    def subscribe(
        self,
        symbol: str,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> QuoteSubscription:
        """Subscribes to a symbol. Several subscriptions to the same symbol share one server subscription."""
        self._assert_alive()
        if not symbol:
            raise TradingViewError("INVALID_ARGUMENT", "A symbol is required")
        opts = {**(options or {}), **kwargs}
        sub = QuoteSubscription(symbol, opts.get("session") or "regular", self._release)
        lst = self._subscriptions.get(sub.key)
        if lst is None:
            lst = []
            self._subscriptions[sub.key] = lst
            self.client.send("quote_add_symbols", [self.id, sub.key])
        else:
            loaded = next((s for s in lst if s.is_loaded), None)
            if loaded is not None:
                sub.seed(loaded)
        lst.append(sub)
        return sub

    def delete(self) -> None:
        """Deletes the session and all its subscriptions. Idempotent."""
        if self._deleted:
            return
        self._deleted = True
        if not self.client.is_closed:
            self.client.send("quote_delete_session", [self.id])
        self.client.unregister_session(self.id)
        for lst in list(self._subscriptions.values()):
            for sub in list(lst):
                sub.close()
        self._subscriptions.clear()

    def _release(self, subscription: QuoteSubscription) -> None:
        lst = self._subscriptions.get(subscription.key)
        if not lst or subscription not in lst:
            return
        lst.remove(subscription)
        if not lst:
            self._subscriptions.pop(subscription.key, None)
            if not self._deleted and not self.client.is_closed:
                self.client.send("quote_remove_symbols", [self.id, subscription.key])

    def _assert_alive(self) -> None:
        if self._deleted:
            raise TradingViewError("INVALID_STATE", "The quote session is deleted")

    def _on_client_close(self, error: TradingViewError, expected: bool) -> None:
        if self._deleted:
            return
        self._deleted = True
        if not expected:
            self._emit("error", error)
        for lst in list(self._subscriptions.values()):
            for sub in list(lst):
                sub.handle_close(error, expected)
        self._subscriptions.clear()

    def _on_packet(self, packet: dict[str, Any]) -> None:
        self.client.log("quote", self.id, packet)
        m = packet.get("m")
        p_list = packet.get("p") or []
        key: str | None = None
        if m == "quote_completed" and len(p_list) > 1:
            key = str(p_list[1])
        elif m == "qsd" and len(p_list) > 1 and isinstance(p_list[1], dict):
            key = p_list[1].get("n")
        else:
            return
        if key is None:
            return

        lst = self._subscriptions.get(key)
        if not lst:
            if not self._deleted and not self.client.is_closed:
                self.client.send("quote_remove_symbols", [self.id, key])
            return
        for sub in list(lst):
            sub.handle_packet(packet)
