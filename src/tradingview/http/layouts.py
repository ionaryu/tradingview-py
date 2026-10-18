from __future__ import annotations

from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from .request import AuthHttpOptions, request

LayoutOptions = dict[str, Any]
DrawingPoint = AttrDict
Drawing = AttrDict
GetDrawingsOptions = dict[str, Any]


async def get_chart_token(
    layout_id: str,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """Gets a chart-storage token for a layout (the ID in `tradingview.com/chart/<ID>/`)."""
    opts = {**(options or {}), **kwargs}
    creds = opts.get("credentials")
    user_id = opts.get("userId", opts.get("user_id"))
    authenticated = bool(isinstance(creds, dict) and creds.get("session") and user_id)

    res = await request(
        "https://www.tradingview.com/chart-token",
        {
            "query": {"image_url": layout_id, "user_id": user_id if authenticated else -1},
            "credentials": creds if authenticated else None,
        },
        opts,
    )
    data = res.data
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        raise TradingViewError("NOT_FOUND", "Wrong layout or credentials", {"details": data})
    return str(token)


getChartToken = get_chart_token


async def get_drawings(
    layout_id: str,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[Drawing]:
    """Lists the drawings of a layout."""
    opts = {**(options or {}), **kwargs}
    token = await get_chart_token(layout_id, opts)
    chart_id = opts.get("chartId") or opts.get("chart_id") or "_shared"
    symbol = opts.get("symbol") or ""

    res = await request(
        f"https://charts-storage.tradingview.com/charts-storage/get/layout/{layout_id}/sources",
        {"query": {"chart_id": chart_id, "jwt": token, "symbol": symbol}},
        opts,
    )
    data = res.data
    payload = data.get("payload") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        raise TradingViewError("NOT_FOUND", "Wrong layout, user credentials, or chart id", {"details": data})
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    out: list[Drawing] = []
    for drw in sources.values():
        if isinstance(drw, dict):
            state = drw.get("state") if isinstance(drw.get("state"), dict) else {}
            out.append(AttrDict({**drw, **state}))
    return out


getDrawings = get_drawings
