from __future__ import annotations

from datetime import datetime, timezone
import platform
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from .._types import AttrDict
from ..errors import TradingViewError
from .request import Credentials, HttpOptions, get_set_cookies, request

User = AttrDict
LoginOptions = dict[str, Any]
GetUserOptions = dict[str, Any]


def _cookie_value(headers: Any, name: str) -> str:
    pattern = re.compile(rf"(?:^|[;\s]){re.escape(name)}=([^;]*)")
    for line in get_set_cookies(headers):
        match = pattern.search(line)
        if match:
            return match.group(1)
    return ""


def _text_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _number_or_zero(value: Any) -> float | int:
    if value is None or value == "":
        return 0
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return 0


def _parse_date(value: Any) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    s = str(value).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _user_from_login(user: dict[str, Any], headers: Any) -> User:
    notif = user.get("notification_count") or {}
    return AttrDict(
        {
            "id": _number_or_zero(user.get("id")),
            "username": user.get("username"),
            "firstName": _text_or_empty(user.get("first_name")),
            "lastName": _text_or_empty(user.get("last_name")),
            "reputation": _number_or_zero(user.get("reputation")),
            "following": _number_or_zero(user.get("following")),
            "followers": _number_or_zero(user.get("followers")),
            "notifications": {
                "user": _number_or_zero(notif.get("user")),
                "following": _number_or_zero(notif.get("following")),
            },
            "session": _cookie_value(headers, "sessionid"),
            "signature": _cookie_value(headers, "sessionid_sign"),
            "sessionHash": _text_or_empty(user.get("session_hash")),
            "privateChannel": _text_or_empty(user.get("private_channel")),
            "authToken": _text_or_empty(user.get("auth_token")),
            "joinDate": _parse_date(user.get("date_joined")),
        }
    )


async def login_user(options: dict[str, Any] | None = None, **kwargs: Any) -> User:
    """Signs in with a username/email and password and returns the account with its session cookies."""
    opts = {**(options or {}), **kwargs}
    remember = opts.get("remember", True)
    user_agent = opts.get("userAgent") or opts.get("user_agent") or "TWAPI/4.0"
    sys_info = f"{platform.release()}; {platform.system().lower()}; {platform.machine()}"

    res = await request(
        "https://www.tradingview.com/accounts/signin/",
        {
            "method": "POST",
            "form": {
                "username": opts.get("username"),
                "password": opts.get("password"),
                "remember": "on" if remember else None,
            },
            "headers": {
                "referer": "https://www.tradingview.com",
                "user-agent": f"{user_agent} ({sys_info})",
            },
        },
        opts,
    )
    data = res.data
    if not data or not isinstance(data, dict):
        raise TradingViewError("AUTH_ERROR", "Unexpected sign-in response")
    if data.get("error"):
        raise TradingViewError("AUTH_ERROR", str(data["error"]), {"details": data})
    if not data.get("user"):
        raise TradingViewError("AUTH_ERROR", "Sign-in response has no user", {"details": data})

    return _user_from_login(data["user"], res.headers)


loginUser = login_user


def _match(page: str, pattern: str) -> str | None:
    m = re.search(pattern, page)
    return m.group(1) if m else None


def _page_number(page: str, pattern: str) -> int | float:
    raw = _match(page, pattern)
    if not raw:
        return 0
    try:
        f = float(raw)
        return int(f) if f.is_integer() else f
    except ValueError:
        return 0


def _page_text(page: str, pattern: str) -> str:
    return _match(page, pattern) or ""


def _trusted_account_location(location: str) -> str:
    try:
        parsed = urlparse(location)
    except Exception as exc:
        raise TradingViewError("AUTH_ERROR", "Invalid account page URL") from exc
    if not parsed.scheme or not parsed.netloc:
        raise TradingViewError("AUTH_ERROR", "Invalid account page URL")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "tradingview.com" or host.endswith(".tradingview.com")):
        raise TradingViewError("AUTH_ERROR", "Account page redirects outside TradingView")
    return location


def parse_user_page(page: str, credentials: dict[str, Any]) -> User:
    """Parses the account embedded in a TradingView HTML page."""
    return AttrDict(
        {
            "id": _page_number(page, r'"id":([0-9]{1,10}),'),
            "username": _page_text(page, r'"username":"(.*?)"'),
            "firstName": _page_text(page, r'"first_name":"(.*?)"'),
            "lastName": _page_text(page, r'"last_name":"(.*?)"'),
            "reputation": _page_number(page, r'"reputation":(.*?),'),
            "following": _page_number(page, r',"following":([0-9]*?),'),
            "followers": _page_number(page, r',"followers":([0-9]*?),'),
            "notifications": {
                "following": _page_number(page, r'"notification_count":\{"following":([0-9]*),'),
                "user": _page_number(page, r'"notification_count":\{"following":[0-9]*,"user":([0-9]*)'),
            },
            "session": credentials.get("session", ""),
            "signature": credentials.get("signature") or "",
            "sessionHash": _page_text(page, r'"session_hash":"(.*?)"'),
            "privateChannel": _page_text(page, r'"private_channel":"(.*?)"'),
            "authToken": _page_text(page, r'"auth_token":"(.*?)"'),
            "joinDate": _parse_date(_page_text(page, r'"date_joined":"(.*?)"')),
        }
    )


parseUserPage = parse_user_page


async def get_user(
    credentials: dict[str, Any] | None,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> User:
    """Loads the account behind `sessionid` (and `sessionid_sign`) cookies."""
    if not credentials or not credentials.get("session"):
        raise TradingViewError("INVALID_ARGUMENT", "A session cookie is required")
    opts = {**(options or {}), **kwargs}
    max_redirects = int(opts.get("maxRedirects", opts.get("max_redirects", 5)))
    location = _trusted_account_location(opts.get("location") or "https://www.tradingview.com/chart/")

    redirects = 0
    while True:
        res = await request(location, {"credentials": credentials, "redirect": "manual"}, opts)
        status = res.status
        text = res.text
        headers = res.headers
        if 200 <= status < 300 and "auth_token" in text:
            user = parse_user_page(text, credentials)
            if user.authToken:
                return user

        next_loc = headers.get("location")
        resolved = urljoin(location, next_loc) if (300 <= status < 400 and next_loc) else None
        if not resolved or resolved == location:
            raise TradingViewError("AUTH_ERROR", "Wrong or expired sessionid/signature")
        if redirects >= max_redirects:
            raise TradingViewError("AUTH_ERROR", "Too many redirects (possible WAF or geo-restriction)")
        location = _trusted_account_location(resolved)
        redirects += 1


getUser = get_user
