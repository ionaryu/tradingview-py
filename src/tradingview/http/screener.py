from __future__ import annotations

import re
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from .request import AuthHttpOptions, request

ScreenerFilter = dict[str, Any]
ScreenerQuery = dict[str, Any]
ScreenerRow = AttrDict
ScreenerResult = AttrDict

_MARKET_RE = re.compile(r"^[a-z][a-z0-9_-]*$", re.IGNORECASE)


def _is_safe_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


async def get_screener(
    query: dict[str, Any] | Any,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ScreenerResult:
    """One scanner page."""
    opts = {**(options or {}), **kwargs}
    q = query if isinstance(query, dict) else {}
    market = q.get("market") if q.get("market") is not None else "global"
    rng = q.get("range") if q.get("range") is not None else [0, 50]
    columns = q.get("columns")

    if (
        not isinstance(market, str)
        or not _MARKET_RE.match(market)
        or not isinstance(columns, list)
        or len(columns) == 0
        or any(not isinstance(c, str) or not c.strip() for c in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(rng, (list, tuple))
        or len(rng) != 2
        or not all(_is_safe_int(x) for x in rng)
        or rng[0] < 0
        or rng[1] <= rng[0]
    ):
        raise TradingViewError("INVALID_ARGUMENT", "Invalid screener market, columns or page range")

    json_body: dict[str, Any] = {
        "columns": columns,
        "range": list(rng),
        "filter": q.get("filter") if q.get("filter") is not None else [],
    }
    if q.get("sort") is not None:
        json_body["sort"] = q["sort"]
    if q.get("symbols") is not None:
        json_body["symbols"] = {"tickers": q["symbols"]}

    res = await request(
        f"https://scanner.tradingview.com/{market}/scan",
        {
            "method": "POST",
            "credentials": opts.get("credentials"),
            "headers": {"origin": "https://www.tradingview.com"},
            "json": json_body,
        },
        opts,
    )
    status = res.status
    data = res.data
    total_count = data.get("totalCount") if isinstance(data, dict) else None
    rows_data = data.get("data") if isinstance(data, dict) else None

    if (
        status < 200
        or status >= 300
        or not isinstance(data, dict)
        or not _is_safe_int(total_count)
        or total_count < 0
        or not isinstance(rows_data, list)
        or any(
            not isinstance(r, dict)
            or not isinstance(r.get("s"), str)
            or not isinstance(r.get("d"), list)
            or len(r["d"]) != len(columns)
            for r in rows_data
        )
    ):
        raise TradingViewError("HTTP_ERROR", f"Unexpected screener response (HTTP {status})")

    return AttrDict(
        {
            "totalCount": total_count,
            "rows": [
                AttrDict(
                    {
                        "symbol": r["s"],
                        "values": {col: r["d"][idx] for idx, col in enumerate(columns)},
                    }
                )
                for r in rows_data
            ],
        }
    )


getScreener = get_screener
