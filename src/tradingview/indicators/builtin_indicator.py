from __future__ import annotations

import math
import time
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError

BuiltInIndicatorType = str
BuiltInIndicatorOption = str


def _js_typeof(val: Any) -> str:
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)):
        return "number"
    if isinstance(val, str):
        return "string"
    return type(val).__name__


def _default_options(indicator_type: str) -> dict[str, Any] | None:
    now = int(time.time() * 1000)
    profile = {
        "rowsLayout": "Number Of Rows",
        "rows": 24,
        "volume": "Up/Down",
        "vaVolume": 70,
    }
    if indicator_type == "Volume@tv-basicstudies-241":
        return {"length": 20, "col_prev_close": False}
    if indicator_type == "VbPFixed@tv-basicstudies-241":
        return {
            **profile,
            "subscribeRealtime": False,
            "first_bar_time": math.nan,
            "last_bar_time": now,
            "extendToRight": False,
            "mapRightBoundaryToBarStartTime": True,
        }
    if indicator_type in ("VbPFixed@tv-basicstudies-241!", "VbPFixed@tv-volumebyprice-53!"):
        return {
            **profile,
            "subscribeRealtime": False,
            "first_bar_time": math.nan,
            "last_bar_time": now,
        }
    if indicator_type == "VbPSessions@tv-volumebyprice-53":
        return {**profile, "extendPocRight": False}
    if indicator_type == "VbPSessionsRough@tv-volumebyprice-53!":
        return {"volume": "Up/Down", "vaVolume": 70}
    if indicator_type == "VbPSessionsDetailed@tv-volumebyprice-53!":
        return {
            "volume": "Up/Down",
            "vaVolume": 70,
            "subscribeRealtime": False,
            "first_visible_bar_time": math.nan,
            "last_visible_bar_time": now,
        }
    if indicator_type == "VbPVisible@tv-volumebyprice-53":
        return {
            **profile,
            "subscribeRealtime": False,
            "first_visible_bar_time": math.nan,
            "last_visible_bar_time": now,
        }
    return None


class BuiltInIndicator:
    """A built-in TradingView study such as Volume or Volume Profile."""

    def __init__(self, indicator_type: str, options: dict[str, Any] | None = None) -> None:
        if not indicator_type:
            raise TradingViewError("INVALID_ARGUMENT", "A built-in indicator type is required")
        self.type: str = indicator_type
        self._defaults = _default_options(indicator_type)
        self.options = AttrDict(self._defaults or {})
        for k, v in (options or {}).items():
            self.set_option(k, v)

    def set_option(self, key: str, value: Any, force: bool = False) -> BuiltInIndicator:
        """Changes an option. For known types, key and value type are validated unless `force` is True."""
        if not force and self._defaults is not None:
            if key not in self._defaults:
                raise TradingViewError("INVALID_ARGUMENT", f"Option '{key}' is not allowed for '{self.type}'")
            expected = _js_typeof(self._defaults[key])
            if _js_typeof(value) != expected:
                raise TradingViewError("INVALID_ARGUMENT", f"Option '{key}' must be a {expected}")
        self.options[key] = value
        return self

    setOption = set_option

    def to_study_inputs(self) -> dict[str, Any]:
        """Parameters sent with `create_study` / `modify_study`."""
        return dict(self.options)

    toStudyInputs = to_study_inputs
