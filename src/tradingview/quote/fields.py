from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .._types import AttrDict

QuoteField = str
QuoteFieldPreset = str
QuoteData = AttrDict

ALL_QUOTE_FIELDS: list[str] = [
    "base-currency-logoid",
    "ch",
    "chp",
    "currency-logoid",
    "currency_code",
    "current_session",
    "description",
    "exchange",
    "format",
    "fractional",
    "is_tradable",
    "language",
    "local_description",
    "logoid",
    "lp",
    "lp_time",
    "minmov",
    "minmove2",
    "original_name",
    "pricescale",
    "pro_name",
    "short_name",
    "type",
    "update_mode",
    "volume",
    "ask",
    "bid",
    "fundamentals",
    "high_price",
    "low_price",
    "open_price",
    "prev_close_price",
    "rch",
    "rchp",
    "rtc",
    "rtc_time",
    "status",
    "industry",
    "basic_eps_net_income",
    "beta_1_year",
    "market_cap_basic",
    "earnings_per_share_basic_ttm",
    "price_earnings_ttm",
    "sector",
    "dividends_yield",
    "timezone",
    "country_code",
    "provider_id",
]


def resolve_quote_fields(fields: str | Sequence[str] | None = "all") -> list[str]:
    """Resolves a preset or explicit list into field names."""
    if fields is None:
        return list(ALL_QUOTE_FIELDS)
    if isinstance(fields, (list, tuple)):
        return list(fields) if len(fields) > 0 else list(ALL_QUOTE_FIELDS)
    return ["lp"] if fields == "price" else list(ALL_QUOTE_FIELDS)


resolveQuoteFields = resolve_quote_fields
