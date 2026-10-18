from __future__ import annotations

import asyncio
from typing import Any, Literal

TradingViewErrorCode = Literal[
    "PROTOCOL_ERROR",
    "CONNECTION_ERROR",
    "DISCONNECTED",
    "AUTH_ERROR",
    "SYMBOL_ERROR",
    "SERIES_ERROR",
    "CRITICAL_ERROR",
    "STUDY_ERROR",
    "QUOTE_ERROR",
    "PARSE_ERROR",
    "INVALID_STATE",
    "INVALID_ARGUMENT",
    "HTTP_ERROR",
    "NOT_FOUND",
    "NO_DATA",
    "TIMEOUT",
    "ABORTED",
    "CALLBACK_ERROR",
]

TradingViewErrorOptions = dict[str, Any]


class TradingViewError(Exception):
    """Every error produced by this library is a `TradingViewError`."""

    name: str = "TradingViewError"
    code: TradingViewErrorCode
    details: Any
    message: str

    def __init__(
        self,
        code: TradingViewErrorCode,
        message: str,
        options: dict[str, Any] | None = None,
        *,
        details: Any = None,
        cause: BaseException | Any | None = None,
    ) -> None:
        super().__init__(message)
        opts = options or {}
        self.code = code
        self.message = message
        self.details = details if details is not None else opts.get("details")
        actual_cause = cause if cause is not None else opts.get("cause")
        if isinstance(actual_cause, BaseException):
            self.__cause__ = actual_cause
        self.cause = actual_cause


def to_trading_view_error(
    error: Any,
    fallback_code: TradingViewErrorCode = "CONNECTION_ERROR",
) -> TradingViewError:
    """Normalises any raised value into a `TradingViewError`."""
    if isinstance(error, TradingViewError):
        return error
    if isinstance(error, asyncio.CancelledError):
        return TradingViewError("ABORTED", str(error) or "Aborted", {"cause": error})
    if isinstance(error, BaseException):
        err_name = getattr(error, "name", None) or type(error).__name__
        if err_name == "AbortError":
            return TradingViewError("ABORTED", str(error) or "Aborted", {"cause": error})
        return TradingViewError(fallback_code, str(error), {"cause": error})
    return TradingViewError(fallback_code, str(error), {"details": error})


toTradingViewError = to_trading_view_error
