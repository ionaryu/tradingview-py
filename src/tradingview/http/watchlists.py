from __future__ import annotations

from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from .request import Credentials, HttpOptions, request
from .screener import ScreenerQuery, ScreenerResult, _is_safe_int, get_screener

Watchlist = AttrDict
WatchlistOptions = dict[str, Any]
HotlistKind = str
HotlistQuery = dict[str, Any]


async def get_watchlists(options: dict[str, Any] | None = None, **kwargs: Any) -> list[Watchlist]:
    """Reads all watchlists belonging to the authenticated account. Never modifies them."""
    opts = {**(options or {}), **kwargs}
    creds = opts.get("credentials")
    if not isinstance(creds, dict) or not creds.get("session"):
        raise TradingViewError("INVALID_ARGUMENT", "getWatchlists requires account credentials")

    res = await request(
        "https://www.tradingview.com/api/v1/symbols_list/all/",
        {
            "credentials": creds,
            "headers": {"origin": "https://www.tradingview.com"},
            "redirect": "manual",
        },
        opts,
    )
    status = res.status
    data = res.data
    if status in (401, 403) or (300 <= status < 400):
        raise TradingViewError("AUTH_ERROR", f"Watchlist access rejected (HTTP {status})")
    if (
        status < 200
        or status >= 300
        or not isinstance(data, list)
        or any(
            not isinstance(lst, dict)
            or not _is_safe_int(lst.get("id"))
            or not isinstance(lst.get("name"), str)
            or not isinstance(lst.get("symbols"), list)
            or any(not isinstance(sym, str) for sym in lst["symbols"])
            for lst in data
        )
    ):
        raise TradingViewError("HTTP_ERROR", f"Unexpected watchlist response (HTTP {status})")
    return [AttrDict(lst) for lst in data]


getWatchlists = get_watchlists

_RANKINGS: dict[str, dict[str, str]] = {
    "gainers": {"sortBy": "change", "sortOrder": "desc"},
    "losers": {"sortBy": "change", "sortOrder": "asc"},
    "mostActive": {"sortBy": "volume", "sortOrder": "desc"},
    "volumeGainers": {"sortBy": "relative_volume_10d_calc", "sortOrder": "desc"},
}


async def get_hotlist(
    query: dict[str, Any] | Any,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ScreenerResult:
    """Scanner-ranked lists."""
    opts = {**(options or {}), **kwargs}
    q = query if isinstance(query, dict) else {}
    kind = q.get("kind")
    if not isinstance(kind, str) or kind not in _RANKINGS:
        raise TradingViewError("INVALID_ARGUMENT", "Unknown hotlist kind")
    return await get_screener(
        {
            **q,
            "market": q.get("market") if q.get("market") is not None else "america",
            "columns": (
                q["columns"]
                if q.get("columns") is not None
                else ["name", "close", "change", "volume", "relative_volume_10d_calc"]
            ),
            "filter": (
                q["filter"]
                if q.get("filter") is not None
                else [{"left": "type", "operation": "equal", "right": "stock"}]
            ),
            "sort": _RANKINGS[kind],
        },
        opts,
    )


getHotlist = get_hotlist
