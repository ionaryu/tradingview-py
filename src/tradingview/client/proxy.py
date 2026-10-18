from __future__ import annotations

import asyncio
import base64
import gzip
import socket
import ssl
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
import zlib

from .._types import AbortError, AttrDict, FetchHeaders, FetchResponse
from ..errors import TradingViewError
from .transport import TransportFactory, ws_transport_with

ProxyTlsOptions = dict[str, Any]
ProxyOptions = dict[str, Any]
ProxyAdapter = AttrDict

REDIRECTS = {301, 302, 303, 307, 308}
NULL_BODY = {101, 103, 204, 205, 304}


def _parse_proxy_url(proxy: str | Any) -> Any:
    raw = str(proxy)
    try:
        parsed = urlparse(raw)
    except Exception as exc:
        raise TradingViewError("INVALID_ARGUMENT", "Invalid proxy URL") from exc
    if not parsed.scheme or not parsed.hostname:
        raise TradingViewError("INVALID_ARGUMENT", "Invalid proxy URL")
    protocol = f"{parsed.scheme.lower()}:"
    if protocol not in ("http:", "https:"):
        raise TradingViewError(
            "INVALID_ARGUMENT",
            f'Unsupported proxy protocol "{protocol}": use an http(s) proxy URL or pass an Agent (e.g. for SOCKS)',
        )
    return parsed


def _proxy_authorization(parsed: Any) -> str | None:
    if not parsed.username and not parsed.password:
        return None
    user = unquote(parsed.username or "")
    pw = unquote(parsed.password or "")
    token = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _proxy_host_label(parsed: Any) -> str:
    host = parsed.hostname or "localhost"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port:
        return f"{host}:{parsed.port}"
    return host


def _build_ssl_context(tls_opts: dict[str, Any] | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not tls_opts:
        return ctx
    if tls_opts.get("rejectUnauthorized") is False or tls_opts.get("reject_unauthorized") is False:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    ca = tls_opts.get("ca")
    if ca is not None:
        items = ca if isinstance(ca, (list, tuple)) else [ca]
        for item in items:
            pem = item.decode("utf-8") if isinstance(item, (bytes, bytearray)) else str(item)
            ctx.load_verify_locations(cadata=pem)
    return ctx


async def _open_tunnel_streams(
    parsed_proxy: Any,
    target_host: str,
    target_port: int,
    options: dict[str, Any],
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
    secure_proxy = parsed_proxy.scheme.lower() == "https"
    proxy_host = parsed_proxy.hostname or "127.0.0.1"
    proxy_port = parsed_proxy.port or (443 if secure_proxy else 80)
    target_label = f"[{target_host}]:{target_port}" if ":" in target_host and not target_host.startswith("[") else f"{target_host}:{target_port}"
    proxy_label = _proxy_host_label(parsed_proxy)
    timeout_ms = int(options.get("connectTimeoutMs", options.get("connect_timeout_ms", 20_000)))
    timeout_s = timeout_ms / 1000.0
    tls_opts = options.get("tls")
    ssl_ctx = _build_ssl_context(tls_opts) if secure_proxy else None

    async def _do_connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            reader, writer = await asyncio.open_connection(
                proxy_host,
                proxy_port,
                ssl=ssl_ctx,
                server_hostname=proxy_host if secure_proxy else None,
            )
        except Exception as exc:
            raise TradingViewError(
                "CONNECTION_ERROR",
                f"Proxy {proxy_label} is unreachable: {exc}",
                {"cause": exc},
            ) from exc

        auth = _proxy_authorization(parsed_proxy)
        lines = [
            f"CONNECT {target_label} HTTP/1.1",
            f"Host: {target_label}",
        ]
        if auth:
            lines.append(f"Proxy-Authorization: {auth}")
        lines.append("\r\n")
        writer.write("\r\n".join(lines).encode("latin1"))
        await writer.drain()

        status_line = await reader.readline()
        if not status_line:
            writer.close()
            raise TradingViewError("CONNECTION_ERROR", f"Proxy {proxy_label} closed connection during CONNECT")
        parts = status_line.decode("latin1", errors="replace").strip().split(" ", 2)
        status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        while True:
            hdr_line = await reader.readline()
            if not hdr_line or hdr_line in (b"\r\n", b"\n"):
                break

        if status_code != 200:
            writer.close()
            raise TradingViewError(
                "CONNECTION_ERROR",
                f"Proxy {proxy_label} refused a tunnel to {target_label} (HTTP {status_code})",
                {"details": {"status": status_code}},
            )
        return reader, writer

    try:
        reader, writer = await asyncio.wait_for(_do_connect(), timeout=timeout_s)
        return reader, writer, target_label
    except asyncio.TimeoutError as exc:
        raise TradingViewError(
            "TIMEOUT",
            f"Proxy {proxy_label} did not open a tunnel to {target_label} in {timeout_ms} ms",
        ) from exc


def _open_blocking_tunnel_socket(
    parsed_proxy: Any,
    target_host: str,
    target_port: int,
    options: dict[str, Any],
) -> socket.socket:
    """Opens a blocking socket through the HTTP(S) proxy CONNECT tunnel, then sets it non-blocking for websockets."""
    secure_proxy = parsed_proxy.scheme.lower() == "https"
    proxy_host = parsed_proxy.hostname or "127.0.0.1"
    proxy_port = parsed_proxy.port or (443 if secure_proxy else 80)
    target_label = f"[{target_host}]:{target_port}" if ":" in target_host and not target_host.startswith("[") else f"{target_host}:{target_port}"
    proxy_label = _proxy_host_label(parsed_proxy)
    timeout_ms = int(options.get("connectTimeoutMs", options.get("connect_timeout_ms", 20_000)))
    timeout_s = timeout_ms / 1000.0
    tls_opts = options.get("tls")

    try:
        raw_sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout_s)
    except TimeoutError as exc:
        raise TradingViewError(
            "TIMEOUT",
            f"Proxy {proxy_label} did not open a tunnel to {target_label} in {timeout_ms} ms",
        ) from exc
    except Exception as exc:
        raise TradingViewError(
            "CONNECTION_ERROR",
            f"Proxy {proxy_label} is unreachable: {exc}",
            {"cause": exc},
        ) from exc

    sock: socket.socket = raw_sock
    try:
        if secure_proxy:
            ctx = _build_ssl_context(tls_opts)
            sock = ctx.wrap_socket(raw_sock, server_hostname=proxy_host)
            sock.settimeout(timeout_s)

        auth = _proxy_authorization(parsed_proxy)
        lines = [
            f"CONNECT {target_label} HTTP/1.1",
            f"Host: {target_label}",
        ]
        if auth:
            lines.append(f"Proxy-Authorization: {auth}")
        lines.append("\r\n")
        sock.sendall("\r\n".join(lines).encode("latin1"))

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk

        header_text = buf.split(b"\r\n\r\n", 1)[0].decode("latin1", errors="replace")
        first_line = header_text.splitlines()[0] if header_text else ""
        parts = first_line.split(" ", 2)
        status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if status_code != 200:
            sock.close()
            raise TradingViewError(
                "CONNECTION_ERROR",
                f"Proxy {proxy_label} refused a tunnel to {target_label} (HTTP {status_code})",
                {"details": {"status": status_code}},
            )
        sock.setblocking(False)
        return sock
    except TradingViewError:
        raise
    except TimeoutError as exc:
        sock.close()
        raise TradingViewError(
            "TIMEOUT",
            f"Proxy {proxy_label} did not open a tunnel to {target_label} in {timeout_ms} ms",
        ) from exc
    except Exception as exc:
        sock.close()
        raise TradingViewError(
            "CONNECTION_ERROR",
            f"Proxy {proxy_label} is unreachable: {exc}",
            {"cause": exc},
        ) from exc


def _decode_body(body: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").strip().lower()
    if enc in ("gzip", "x-gzip"):
        return gzip.decompress(body)
    if enc == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


async def _read_http_response(reader: asyncio.StreamReader, method: str) -> tuple[int, str, FetchHeaders, bytes]:
    status_line = await reader.readline()
    if not status_line:
        raise ConnectionError("Empty HTTP response from target")
    parts = status_line.decode("latin1", errors="replace").strip().split(" ", 2)
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    status_text = parts[2] if len(parts) > 2 else ""

    headers = FetchHeaders()
    while True:
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("latin1", errors="replace").rstrip("\r\n")
        if ":" in decoded:
            k, v = decoded.split(":", 1)
            headers.append(k.strip(), v.strip())

    if method == "HEAD" or status in NULL_BODY:
        body = b""
    elif (headers.get("transfer-encoding") or "").lower() == "chunked":
        chunks: list[bytes] = []
        while True:
            size_line = await reader.readline()
            if not size_line:
                break
            size_str = size_line.decode("latin1").strip().split(";", 1)[0]
            size = int(size_str, 16)
            if size == 0:
                await reader.readline()
                break
            chunks.append(await reader.readexactly(size))
            await reader.readexactly(2)
        body = b"".join(chunks)
    elif headers.has("content-length"):
        length = int(headers.get("content-length") or "0")
        body = await reader.readexactly(length) if length > 0 else b""
    else:
        body = await reader.read()

    if method != "HEAD" and headers.has("content-encoding"):
        body = _decode_body(body, headers.get("content-encoding"))
        headers.delete("content-encoding")
        headers.delete("content-length")

    return status, status_text, headers, body


async def _send_over_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    parsed_url: Any,
    method: str,
    headers: FetchHeaders,
    body: bytes | None,
) -> tuple[int, str, FetchHeaders, bytes]:
    try:
        path = parsed_url.path or "/"
        if parsed_url.query:
            path = f"{path}?{parsed_url.query}"
        host_hdr = parsed_url.netloc
        req_lines = [f"{method} {path} HTTP/1.1", f"Host: {host_hdr}"]
        has_accept_enc = False
        has_conn = False
        for k, v in headers.items():
            low = k.lower()
            if low == "host":
                continue
            if low == "accept-encoding":
                has_accept_enc = True
            if low == "connection":
                has_conn = True
            req_lines.append(f"{k}: {v}")
        if not has_accept_enc:
            req_lines.append("Accept-Encoding: gzip, deflate")
        if not has_conn:
            req_lines.append("Connection: close")
        if body is not None:
            req_lines.append(f"Content-Length: {len(body)}")
        req_lines.append("\r\n")
        writer.write("\r\n".join(req_lines).encode("latin1"))
        if body:
            writer.write(body)
        await writer.drain()
        return await _read_http_response(reader, method)
    finally:
        writer.close()


def create_proxy(proxy: str | Any, options: dict[str, Any] | None = None, **kwargs: Any) -> ProxyAdapter:
    """Routes HTTP requests and websockets through an HTTP(S) CONNECT proxy or custom Agent."""
    opts = {**(options or {}), **kwargs}
    is_custom_agent = not isinstance(proxy, str) and (
        hasattr(proxy, "createConnection") or hasattr(proxy, "create_connection") or hasattr(proxy, "create_socket")
    )

    parsed_proxy = None if is_custom_agent else _parse_proxy_url(proxy)
    ssl_ctx = _build_ssl_context(opts.get("tls"))

    async def _connect_socket_for_ws(url: str) -> socket.socket:
        parsed_target = urlparse(url)
        host = parsed_target.hostname or "localhost"
        port = parsed_target.port or (443 if parsed_target.scheme in ("https", "wss") else 80)
        if is_custom_agent:
            fn = getattr(proxy, "createConnection", None) or getattr(proxy, "create_connection", None) or getattr(proxy, "create_socket")
            res = fn({"host": host, "hostname": host, "port": port})
            sock = await res if asyncio.iscoroutine(res) else res
            sock.setblocking(False)
            return sock
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _open_blocking_tunnel_socket, parsed_proxy, host, port, opts)

    async def _proxy_fetch(url: str, init: dict[str, Any] | None = None) -> FetchResponse:
        req_init = dict(init or {})
        signal = req_init.get("signal")
        if signal is not None and getattr(signal, "aborted", False):
            reason = getattr(signal, "reason", None)
            raise reason if isinstance(reason, BaseException) else AbortError(str(reason or "This operation was aborted"))

        current_url = str(url)
        method = str(req_init.get("method") or ("POST" if req_init.get("body") is not None else "GET")).upper()
        headers = FetchHeaders(req_init.get("headers"))
        raw_body = req_init.get("body")
        body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
        redirect_policy = req_init.get("redirect", "follow")

        redirects = 0
        while True:
            parsed_u = urlparse(current_url)
            target_host = parsed_u.hostname or "localhost"
            target_port = parsed_u.port or (443 if parsed_u.scheme == "https" else 80)
            target_is_tls = parsed_u.scheme == "https"

            if is_custom_agent:
                fn = getattr(proxy, "createConnection", None) or getattr(proxy, "create_connection", None) or getattr(proxy, "create_socket")
                res = fn({"host": target_host, "hostname": target_host, "port": target_port})
                sock = await res if asyncio.iscoroutine(res) else res
                sock.setblocking(False)
                reader, writer = await asyncio.open_connection(
                    sock=sock,
                    ssl=ssl_ctx if target_is_tls else None,
                    server_hostname=target_host if target_is_tls else None,
                )
            else:
                sock = await asyncio.get_running_loop().run_in_executor(
                    None, _open_blocking_tunnel_socket, parsed_proxy, target_host, target_port, opts
                )
                try:
                    reader, writer = await asyncio.open_connection(
                        sock=sock,
                        ssl=ssl_ctx if target_is_tls else None,
                        server_hostname=target_host if target_is_tls else None,
                    )
                except Exception as exc:
                    sock.close()
                    raise TradingViewError("HTTP_ERROR", str(exc), {"cause": exc}) from exc

            status, status_text, resp_headers, resp_body = await _send_over_stream(
                reader, writer, parsed_u, method, headers, body
            )

            location = resp_headers.get("location")
            if redirect_policy == "manual" or status not in REDIRECTS or not location:
                return FetchResponse(
                    None if (status in NULL_BODY or method == "HEAD") else resp_body,
                    status=status,
                    status_text=status_text,
                    headers=resp_headers,
                    url=current_url,
                    redirected=redirects > 0,
                )
            if redirect_policy == "error":
                raise TypeError(f"Unexpected redirect from {parsed_u.scheme}://{parsed_u.netloc}")
            if redirects >= 20:
                raise TypeError("Too many redirects")

            next_url = urljoin(current_url, location)
            parsed_next = urlparse(next_url)
            if status == 303 or (status in (301, 302) and method == "POST"):
                if method != "HEAD":
                    method = "GET"
                body = None
                for h_name in ("content-type", "content-length", "content-encoding", "content-language", "content-location"):
                    headers.delete(h_name)
            if (parsed_next.scheme, parsed_next.netloc) != (parsed_u.scheme, parsed_u.netloc):
                for h_name in ("authorization", "cookie", "proxy-authorization", "host"):
                    headers.delete(h_name)
            current_url = next_url
            redirects += 1

    transport = ws_transport_with(
        lambda url: {
            "socket_factory": _connect_socket_for_ws,
            "ssl": ssl_ctx if url.startswith("wss:") else None,
        }
    )

    return AttrDict({"fetch": _proxy_fetch, "transport": transport})


createProxy = create_proxy
