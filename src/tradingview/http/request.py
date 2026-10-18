from __future__ import annotations

import asyncio
import json as _json
import re
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import httpx

from .._types import AbortError, AttrDict, FetchHeaders, FetchResponse
from ..errors import TradingViewError, to_trading_view_error

Credentials = dict[str, Any]
HttpOptions = dict[str, Any]
AuthHttpOptions = dict[str, Any]
RequestInit = dict[str, Any]
HttpResponse = AttrDict

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def auth_cookies(credentials: dict[str, Any] | Any | None = None) -> str:
    """Builds the `cookie` header value for credentials."""
    if not credentials:
        return ""
    session = credentials.get("session") if isinstance(credentials, dict) else getattr(credentials, "session", "")
    signature = (
        credentials.get("signature") if isinstance(credentials, dict) else getattr(credentials, "signature", "")
    )
    if not session:
        return ""
    if not signature:
        return f"sessionid={session}"
    return f"sessionid={session};sessionid_sign={signature}"


authCookies = auth_cookies


def _request_url(url: str, query: dict[str, Any] | None = None) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    if not query:
        return url
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in query.items():
        if v is not None:
            if isinstance(v, bool):
                existing[k] = "true" if v else "false"
            else:
                existing[k] = str(v)
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


def _request_body(init: dict[str, Any], headers: dict[str, str]) -> str | None:
    form = init.get("form")
    if form is not None:
        items: list[tuple[str, str]] = []
        for k, v in form.items():
            if v is not None:
                items.append((str(k), str(v)))
        headers["content-type"] = "application/x-www-form-urlencoded"
        return urlencode(items)
    if "json" in init and init["json"] is not None:
        headers["content-type"] = "application/json"
        return _json.dumps(init["json"], separators=(",", ":"))
    return init.get("body")


def _response_data(text: str) -> Any:
    if not text:
        return None
    try:
        parsed = _json.loads(text)
        return AttrDict(parsed) if isinstance(parsed, dict) else parsed
    except Exception:
        return None


async def default_fetch(url: str, init: dict[str, Any] | None = None) -> FetchResponse:
    """Default `httpx`-backed fetch implementation."""
    opts = init or {}
    signal = opts.get("signal")
    if signal is not None and getattr(signal, "aborted", False):
        reason = getattr(signal, "reason", None)
        raise reason if isinstance(reason, BaseException) else AbortError(str(reason or "Aborted"))

    method = opts.get("method") or ("GET" if opts.get("body") is None else "POST")
    headers = dict(opts.get("headers") or {})
    body = opts.get("body")
    redirect_policy = opts.get("redirect", "follow")
    follow_redirects = redirect_policy == "follow"

    async with httpx.AsyncClient(follow_redirects=follow_redirects, timeout=30.0) as client:
        req_coro = client.request(
            method=method,
            url=url,
            headers=headers,
            content=body.encode("utf-8") if isinstance(body, str) else body,
        )
        if signal is not None and hasattr(signal, "add_event_listener"):
            task = asyncio.ensure_future(req_coro)

            def _on_abort() -> None:
                task.cancel()

            signal.add_event_listener("abort", _on_abort)
            try:
                resp = await task
            except asyncio.CancelledError as exc:
                if getattr(signal, "aborted", False):
                    reason = getattr(signal, "reason", None)
                    raise (reason if isinstance(reason, BaseException) else AbortError(str(reason or "Aborted"))) from exc
                raise
            finally:
                signal.remove_event_listener("abort", _on_abort)
        else:
            resp = await req_coro

        fh = FetchHeaders(resp.headers)
        return FetchResponse(
            resp.content,
            status=resp.status_code,
            status_text=resp.reason_phrase,
            headers=fh,
            url=str(resp.url),
            redirected=len(resp.history) > 0,
        )


async def request(
    url: str,
    init: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> HttpResponse:
    """Performs an HTTP request. 5xx statuses raise `TradingViewError('HTTP_ERROR', ...)`."""
    req_init = dict(init or {})
    opts = dict(options or {})
    target_url = _request_url(url, req_init.get("query"))
    parsed_target = urlparse(target_url)

    headers: dict[str, str] = {**(opts.get("headers") or {}), **(req_init.get("headers") or {})}
    cookie = auth_cookies(req_init.get("credentials") or opts.get("credentials"))
    if cookie:
        headers["cookie"] = cookie
    body = _request_body(req_init, headers)

    fetch_impl = opts.get("fetch") or default_fetch
    try:
        response = await fetch_impl(
            target_url,
            {
                "method": req_init.get("method") or ("GET" if body is None else "POST"),
                "headers": headers,
                "body": body,
                "redirect": req_init.get("redirect") or "follow",
                "signal": opts.get("signal"),
            },
        )
        text = await response.text()
    except Exception as error:
        raise to_trading_view_error(error, "HTTP_ERROR") from error

    status = int(response.status)
    if status >= 500:
        raise TradingViewError(
            "HTTP_ERROR",
            f"{parsed_target.netloc} answered HTTP {status}",
            {"details": {"status": status, "body": text[:500]}},
        )

    resp_headers = response.headers if isinstance(response.headers, FetchHeaders) else FetchHeaders(response.headers)
    return AttrDict(
        {
            "status": status,
            "headers": resp_headers,
            "url": getattr(response, "url", None) or target_url,
            "text": text,
            "data": _response_data(text),
        }
    )


def get_set_cookies(headers: Any) -> list[str]:
    """Reads every `set-cookie` header across header implementations."""
    if hasattr(headers, "getSetCookie") and callable(headers.getSetCookie):
        return list(headers.getSetCookie())
    if hasattr(headers, "get_set_cookie") and callable(headers.get_set_cookie):
        return list(headers.get_set_cookie())
    raw = headers.get("set-cookie") if hasattr(headers, "get") else None
    if not raw:
        return []
    return re.split(r",(?=\s*[^;,=\s]+=)", str(raw))


getSetCookies = get_set_cookies
