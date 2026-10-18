from __future__ import annotations

import re

_TIMEFRAME_RE = re.compile(r"^(\d*)([SDWM]?)$", re.IGNORECASE)


def timeframe_seconds(timeframe: str) -> int | None:
    """Approximate duration of one bar in seconds, or `None` for non-time-based resolutions."""
    match = _TIMEFRAME_RE.match(str(timeframe).strip())
    if not match:
        return None
    amount_text, unit_text = match.group(1), match.group(2)
    amount = int(amount_text) if amount_text else 1
    if amount <= 0:
        return None
    unit = unit_text.upper()
    if unit == "":
        return amount * 60 if amount_text else None
    if unit == "S":
        return amount
    if unit == "D":
        return amount * 86_400
    if unit == "W":
        return amount * 604_800
    if unit == "M":
        return amount * 2_592_000
    return None


timeframeSeconds = timeframe_seconds
