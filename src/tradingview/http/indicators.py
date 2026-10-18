from __future__ import annotations

import asyncio
import re
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from ..indicators.pine_indicator import PineIndicator, PineInput
from .request import AuthHttpOptions, Credentials, HttpOptions, request

IndicatorAccess = str
IndicatorSearchResult = AttrDict
GetIndicatorOptions = dict[str, Any]

_built_in_cache: list[Any] | None = None


async def _fetch_filter(f_name: str, options: dict[str, Any]) -> list[Any]:
    res = await request(
        "https://pine-facade.tradingview.com/pine-facade/list",
        {"query": {"filter": f_name}},
        options,
    )
    return res.data if isinstance(res.data, list) else []


def clear_indicator_cache() -> None:
    """Clears the in-memory list of built-in indicators used by `search_indicators`."""
    global _built_in_cache
    _built_in_cache = None


clearIndicatorCache = clear_indicator_cache


def _normalise(value: str = "") -> str:
    return re.sub(r"[^A-Z]", "", str(value or "").upper())


async def search_indicators(
    query: str = "",
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[IndicatorSearchResult]:
    """Searches built-in and community indicators."""
    global _built_in_cache
    opts = {**(options or {}), **kwargs}

    if opts.get("fetch") or _built_in_cache is None:
        b_tasks = [
            asyncio.create_task(_fetch_filter(f, opts))
            for f in ("standard", "candlestick", "fundamental")
        ]
        c_task = asyncio.create_task(
            request(
                "https://www.tradingview.com/pubscripts-suggest-json",
                {"query": {"search": query}},
                opts,
            )
        )
        lists, community = await asyncio.gather(asyncio.gather(*b_tasks), c_task)
        built_ins = [item for sub in lists for item in sub]
        if not opts.get("fetch"):
            _built_in_cache = built_ins
    else:
        built_ins = _built_in_cache
        community = await request(
            "https://www.tradingview.com/pubscripts-suggest-json",
            {"query": {"search": query}},
            opts,
        )

    needle = _normalise(query)
    results: list[IndicatorSearchResult] = []

    def _kind(ind: dict[str, Any]) -> str:
        extra = ind.get("extra")
        return (extra.get("kind") if isinstance(extra, dict) else None) or "study"

    for ind in built_ins:
        extra = ind.get("extra") if isinstance(ind, dict) else None
        short_desc = extra.get("shortDescription", "") if isinstance(extra, dict) else ""
        if needle in _normalise(ind.get("scriptName", "")) or needle in _normalise(short_desc):
            results.append(
                AttrDict(
                    {
                        "id": ind.get("scriptIdPart"),
                        "version": str(ind.get("version", "")),
                        "name": ind.get("scriptName"),
                        "author": {"id": int(ind.get("userId", -1)), "username": "@TRADINGVIEW@"},
                        "image": "",
                        "source": "",
                        "type": _kind(ind),
                        "access": "closed_source",
                    }
                )
            )

    comm_results = (community.data.get("results") if isinstance(community.data, dict) else None) or []
    access_types = ("open_source", "closed_source", "invite_only")
    for ind in comm_results:
        author = ind.get("author") if isinstance(ind.get("author"), dict) else {}
        acc_idx = int(ind.get("access", 0)) - 1
        access = access_types[acc_idx] if 0 <= acc_idx < len(access_types) else "other"
        results.append(
            AttrDict(
                {
                    "id": ind.get("scriptIdPart"),
                    "version": str(ind.get("version", "")),
                    "name": ind.get("scriptName"),
                    "author": {"id": int(author.get("id", -1)), "username": str(author.get("username") or "")},
                    "image": str(ind.get("imageUrl") or ""),
                    "source": str(ind.get("scriptSource") or ""),
                    "type": _kind(ind),
                    "access": access,
                }
            )
        )
    return results


searchIndicators = search_indicators


def _sanitise(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "", value.replace(" ", "_"))


def _parse_inputs(items: list[dict[str, Any]]) -> dict[str, PineInput]:
    inputs: dict[str, PineInput] = {}
    for inp in items:
        inp_id = inp.get("id")
        if inp_id in ("text", "pineId", "pineVersion"):
            continue
        inline_name = _sanitise(str(inp.get("name") or inp_id))
        entry: dict[str, Any] = {
            "name": inp.get("name"),
            "inline": inp.get("inline") or inline_name,
            "internalID": inp.get("internalID") or inline_name,
            "tooltip": inp.get("tooltip"),
            "type": inp.get("type"),
            "value": inp.get("defval"),
            "isHidden": bool(inp.get("isHidden")),
            "isFake": bool(inp.get("isFake")),
        }
        if inp.get("options") is not None:
            entry["options"] = list(inp["options"])
        inputs[str(inp_id)] = AttrDict(entry)
    return inputs


def _parse_plots(styles: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, str]:
    plots: dict[str, str] = {}
    for plot_id, style in styles.items():
        title = _sanitise(str((style.get("title") if isinstance(style, dict) else None) or plot_id))
        titles = list(plots.values())
        if title in titles:
            i = 2
            while f"{title}_{i}" in titles:
                i += 1
            plots[plot_id] = f"{title}_{i}"
        else:
            plots[plot_id] = title
    for plot in items:
        target = plot.get("target")
        if not target:
            continue
        plots[str(plot["id"])] = f"{plots.get(target, target)}_{plot.get('type')}"
    return plots


def parse_indicator_definition(result: dict[str, Any], indicator_id: str, version: str) -> PineIndicator:
    """Converts a `pine-facade/translate` result into a `PineIndicator`."""
    meta = result.get("metaInfo") or {}
    pine_meta = meta.get("pine") if isinstance(meta.get("pine"), dict) else {}
    return PineIndicator(
        {
            "id": meta.get("scriptIdPart") or indicator_id,
            "version": pine_meta.get("version") or version,
            "description": meta.get("description") or "",
            "shortDescription": meta.get("shortDescription") or "",
            "inputs": _parse_inputs(meta.get("inputs") or []),
            "plots": _parse_plots(meta.get("styles") or {}, meta.get("plots") or []),
            "script": result.get("ilTemplate") or "",
        }
    )


parseIndicatorDefinition = parse_indicator_definition


async def get_indicator(
    indicator_id: str,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> PineIndicator:
    """Loads an indicator definition (`STD;RSI`, `PUB;xxxx`, `USER;xxxx`...)."""
    opts = {**(options or {}), **kwargs}
    version = str(opts.get("version") or "last")
    encoded_id = re.sub(r" |%", "%25", indicator_id)
    res = await request(
        f"https://pine-facade.tradingview.com/pine-facade/translate/{encoded_id}/{version}",
        {"credentials": opts.get("credentials")},
        opts,
    )
    data = res.data
    result_obj = data.get("result") if isinstance(data, dict) else None
    meta_info = result_obj.get("metaInfo") if isinstance(result_obj, dict) else None
    if not isinstance(data, dict) or not data.get("success") or not isinstance(meta_info, dict) or meta_info.get("inputs") is None:
        reason = data.get("reason") if isinstance(data, dict) else None
        raise TradingViewError("NOT_FOUND", f'Inexistent or unsupported indicator: "{reason}"', {"details": data})
    return parse_indicator_definition(result_obj, encoded_id, version)


getIndicator = get_indicator


async def get_private_indicators(
    credentials: dict[str, Any],
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[IndicatorSearchResult]:
    """Lists the private (saved) indicators of an account."""
    opts = {**(options or {}), **kwargs}
    res = await request(
        "https://pine-facade.tradingview.com/pine-facade/list",
        {"query": {"filter": "saved"}, "credentials": credentials},
        opts,
    )
    data = res.data
    if not isinstance(data, list):
        raise TradingViewError("AUTH_ERROR", "Unable to list private indicators (check credentials)", {"details": data})

    out: list[IndicatorSearchResult] = []
    for ind in data:
        extra = ind.get("extra") if isinstance(ind.get("extra"), dict) else {}
        out.append(
            AttrDict(
                {
                    "id": ind.get("scriptIdPart"),
                    "version": str(ind.get("version", "")),
                    "name": ind.get("scriptName"),
                    "author": {"id": -1, "username": "@ME@"},
                    "image": str(ind.get("imageUrl") or ""),
                    "source": str(ind.get("scriptSource") or ""),
                    "type": extra.get("kind") or "study",
                    "access": "private",
                }
            )
        )
    return out


getPrivateIndicators = get_private_indicators
