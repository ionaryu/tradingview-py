from __future__ import annotations

import math
import time
from typing import Any, Callable

from .._types import AttrDict
from ..chart.chart_session import ChartSession, MarketOptions, SeriesCompletedInfo
from ..chart.timeframes import timeframe_seconds
from ..chart.types import Candle
from ..errors import TradingViewError
from .operation import to_unix_seconds, validate_symbol

ChartQuery = dict[str, Any]
RangeQuery = dict[str, Any]
HistoryPlan = AttrDict

MAX_CHUNK = 5_000


def _positive_integer(value: Any, name: str, fallback: int) -> int:
    result = fallback if value is None else value
    if isinstance(result, bool) or not isinstance(result, int) or result < 1:
        raise TradingViewError("INVALID_ARGUMENT", f"{name} must be a positive integer")
    return result


def plan_history(query: dict[str, Any]) -> HistoryPlan:
    """Validates a query and computes how many bars to request first."""
    symbol = validate_symbol(query.get("symbol"))
    count = _positive_integer(query.get("count"), "count", 100)
    max_count = _positive_integer(
        query.get("maxCount") if "maxCount" in query else query.get("max_count"),
        "maxCount",
        20_000,
    )
    from_ts = to_unix_seconds(query.get("from") if "from" in query else query.get("from_"), "from")
    to_ts = to_unix_seconds(query.get("to"), "to")
    if from_ts is not None and to_ts is not None and from_ts > to_ts:
        raise TradingViewError("INVALID_ARGUMENT", "from must be before to")
    timeframe = query.get("timeframe") or "D"

    initial = min(count, MAX_CHUNK)
    if from_ts is not None:
        step = timeframe_seconds(timeframe)
        end = to_ts if to_ts is not None else math.floor(time.time())
        initial = math.ceil((end - from_ts) / step) + 2 if step else 1_000
        initial = max(1, min(initial, max_count, MAX_CHUNK))

    chart_type = query.get("chartType") if "chartType" in query else query.get("chart_type")
    chart_inputs = query.get("chartInputs") if "chartInputs" in query else query.get("chart_inputs")
    back_adj = (
        query.get("backAdjustment")
        if "backAdjustment" in query
        else query.get("back_adjustment")
    )
    use_settlement = (
        query.get("useSettlementAsClose")
        if "useSettlementAsClose" in query
        else query.get("use_settlement_as_close")
    )

    return AttrDict(
        {
            "symbol": symbol,
            "count": count,
            "from": from_ts,
            "to": to_ts,
            "maxCount": max_count,
            "timezone": query.get("timezone"),
            "market": AttrDict(
                {
                    "timeframe": timeframe,
                    "count": initial,
                    "to": to_ts,
                    "type": chart_type,
                    "inputs": chart_inputs,
                    "currency": query.get("currency"),
                    "session": query.get("session"),
                    "adjustment": query.get("adjustment"),
                    "backAdjustment": back_adj,
                    "useSettlementAsClose": use_settlement,
                }
            ),
        }
    )


planHistory = plan_history


def select_candles(candles: list[Candle], plan: dict[str, Any]) -> list[Candle]:
    """Selects the requested bars from everything loaded on a chart."""
    result = list(candles)
    to_ts = plan.get("to")
    from_ts = plan.get("from")
    count = int(plan.get("count", 100))
    if to_ts is not None:
        result = [c for c in result if c["time"] <= to_ts]
    if from_ts is not None:
        return [c for c in result if c["time"] >= from_ts]
    return result[-count:] if count > 0 else []


selectCandles = select_candles


def open_market(chart: ChartSession, plan: HistoryPlan) -> None:
    """Opens the market on a chart according to a plan."""
    if plan.get("timezone"):
        chart.set_timezone(plan["timezone"])
    chart.set_market(plan["symbol"], plan["market"])


openMarket = open_market


def load_history(
    chart: ChartSession,
    plan: HistoryPlan,
    deep: bool,
    on_done: Callable[[SeriesCompletedInfo], None],
) -> Callable[[], None]:
    """Loads history: after each series_completed, requests more bars until satisfied or exhausted."""
    previous_size = -1
    done = False

    def _on_completed(info: SeriesCompletedInfo) -> None:
        nonlocal previous_size, done
        if done:
            return
        candles = chart.candles
        to_ts = plan.get("to")
        from_ts = plan.get("from")
        in_range = candles if to_ts is None else [c for c in candles if c["time"] <= to_ts]
        target = int(plan["maxCount"]) if from_ts is not None else int(plan["count"])
        satisfied = (
            (len(in_range) > 0 and in_range[0]["time"] <= from_ts)
            if from_ts is not None
            else len(in_range) >= int(plan["count"])
        )
        exhausted = info.get("dataCompleted") is not None or len(candles) <= previous_size

        if not deep or satisfied or exhausted or len(candles) >= target:
            done = True
            on_done(info)
            return

        previous_size = len(candles)
        missing = MAX_CHUNK if from_ts is not None else int(plan["count"]) - len(in_range)
        chart.fetch_more(max(1, min(missing, MAX_CHUNK, target - len(candles))))

    return chart.on("seriesCompleted", _on_completed)


loadHistory = load_history


def no_data_error(symbol: str, info: SeriesCompletedInfo | None = None) -> TradingViewError:
    """Error for an empty result, with the server's reason when known."""
    reason = (
        " (the server reported an access limit: this range or timeframe may need an account with access)"
        if info and info.get("dataCompleted") == "limit"
        else ""
    )
    return TradingViewError(
        "NO_DATA",
        f"No candles available for {symbol} in the requested range{reason}",
        details=info.get("raw") if info else None,
    )


noDataError = no_data_error
