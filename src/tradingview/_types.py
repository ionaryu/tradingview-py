from __future__ import annotations

import json as _json
from collections.abc import Callable
from typing import Any


class AbortError(Exception):
    """Raised when an operation is aborted via an AbortSignal."""

    name: str = "AbortError"

    def __init__(self, message: str = "This operation was aborted") -> None:
        super().__init__(message)
        self.message = message


class AbortSignal:
    """JavaScript-compatible AbortSignal for Python asyncio operations."""

    def __init__(self) -> None:
        self._aborted: bool = False
        self._reason: Any = None
        self._listeners: list[Callable[[], Any]] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Any:
        return self._reason

    def add_event_listener(
        self,
        event: str,
        listener: Callable[[], Any],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if event != "abort":
            return
        if self._aborted:
            listener()
            return
        if listener not in self._listeners:
            self._listeners.append(listener)

    addEventListener = add_event_listener

    def remove_event_listener(self, event: str, listener: Callable[[], Any]) -> None:
        if event == "abort" and listener in self._listeners:
            self._listeners.remove(listener)

    removeEventListener = remove_event_listener

    def _trigger(self, reason: Any = None) -> None:
        if self._aborted:
            return
        self._aborted = True
        self._reason = reason if reason is not None else AbortError("This operation was aborted")
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                pass
        self._listeners.clear()


class AbortController:
    """JavaScript-compatible AbortController for cancelling async operations."""

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self, reason: Any = None) -> None:
        self.signal._trigger(reason)


class FetchHeaders:
    """Case-insensitive HTTP headers container supporting `.get()`, `.get_set_cookie()`, and `.getSetCookie()`."""

    def __init__(self, init: Any = None) -> None:
        self._items: list[tuple[str, str]] = []
        if init is None:
            return
        if isinstance(init, FetchHeaders):
            self._items = list(init._items)
        elif hasattr(init, "multi_items"):
            for k, v in init.multi_items():
                self._items.append((str(k), str(v)))
        elif isinstance(init, dict):
            for k, v in init.items():
                if isinstance(v, list):
                    for item in v:
                        self._items.append((str(k), str(item)))
                else:
                    self._items.append((str(k), str(v)))
        elif isinstance(init, (list, tuple)):
            for k, v in init:
                self._items.append((str(k), str(v)))

    def append(self, name: str, value: str) -> None:
        self._items.append((str(name), str(value)))

    def set(self, name: str, value: str) -> None:
        low = name.lower()
        self._items = [(k, v) for k, v in self._items if k.lower() != low]
        self._items.append((str(name), str(value)))

    def delete(self, name: str) -> None:
        low = name.lower()
        self._items = [(k, v) for k, v in self._items if k.lower() != low]

    def has(self, name: str) -> bool:
        low = name.lower()
        return any(k.lower() == low for k, _ in self._items)

    def get(self, name: str, default: str | None = None) -> str | None:
        low = name.lower()
        vals = [v for k, v in self._items if k.lower() == low]
        if not vals:
            return default
        if low == "set-cookie":
            return ", ".join(vals)
        return vals[-1]

    def get_set_cookie(self) -> list[str]:
        return [v for k, v in self._items if k.lower() == "set-cookie"]

    getSetCookie = get_set_cookie

    def items(self) -> list[tuple[str, str]]:
        return list(self._items)

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in self._items:
            out[k.lower()] = v
        return out

    def __contains__(self, name: str) -> bool:
        return self.has(name)


class FetchResponse:
    """Minimal Web Fetch API compatible Response used by default fetch, proxy fetch, and test mocks."""

    def __init__(
        self,
        body: str | bytes | None = "",
        options: dict[str, Any] | None = None,
        *,
        status: int = 200,
        status_text: str = "",
        headers: Any = None,
        url: str = "",
        redirected: bool = False,
    ) -> None:
        opts = options or {}
        self.status: int = int(opts.get("status", status))
        self.status_text: str = str(opts.get("statusText", status_text))
        self.statusText: str = self.status_text
        self.headers = FetchHeaders(opts.get("headers", headers))
        self.url: str = str(opts.get("url", url))
        self.redirected: bool = bool(opts.get("redirected", redirected))
        if body is None:
            self._bytes = b""
        elif isinstance(body, bytes):
            self._bytes = body
        else:
            self._bytes = str(body).encode("utf-8")

    async def text(self) -> str:
        return self._bytes.decode("utf-8", errors="replace")

    async def json(self) -> Any:
        return _json.loads(await self.text())

    async def array_buffer(self) -> bytes:
        return self._bytes

    arrayBuffer = array_buffer


class AttrDict(dict):
    """A dict subclass that supports attribute-style access (obj.key and obj['key'])
    and recursively wraps nested dicts/lists so callers can use either Python dict
    indexing or JS/TS dot notation.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for k, v in list(self.items()):
            super().__setitem__(k, _wrap(v))

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            camel = _snake_to_camel(name)
            if camel in self:
                return self[camel]
            snake = _camel_to_snake(name)
            if snake in self:
                return self[snake]
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self[name] = _wrap(value)

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, _wrap(value))


def _wrap(value: Any) -> Any:
    if isinstance(value, AttrDict):
        return value
    if isinstance(value, dict):
        return AttrDict(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def _snake_to_camel(name: str) -> str:
    if "_" not in name:
        return name
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
