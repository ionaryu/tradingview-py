from __future__ import annotations

import math
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError

RelAbsValue = AttrDict
TradeReport = AttrDict
PerformanceReport = AttrDict
FromTo = AttrDict
StrategyReport = AttrDict
StrategyReportChange = str
StrategySummary = AttrDict


def parse_trades(trades: Any) -> list[TradeReport]:
    """Converts raw trades (oldest first) into readable trades (most recent first)."""
    if not isinstance(trades, list) or any(not isinstance(t, dict) for t in trades):
        raise TradingViewError("PARSE_ERROR", "Strategy trades must be an array of records")
    out: list[TradeReport] = []
    for t in reversed(trades):
        e = t.get("e") or {}
        x = t.get("x") or {}
        tp_str = str(e.get("tp") or "")
        out.append(
            AttrDict(
                {
                    "entry": {
                        "name": e.get("c"),
                        "type": "short" if tp_str.startswith("s") else "long",
                        "value": e.get("p"),
                        "time": e.get("tm"),
                    },
                    "exit": {
                        "name": x.get("c"),
                        "value": x.get("p"),
                        "time": x.get("tm"),
                    },
                    "quantity": t.get("q"),
                    "profit": t.get("tp"),
                    "cumulative": t.get("cp"),
                    "runup": t.get("rn"),
                    "drawdown": t.get("dd"),
                }
            )
        )
    return out


parseTrades = parse_trades


def merge_strategy_report(target: dict[str, Any], report: Any) -> list[str]:
    """Merges a raw report into `target`; returns the changed parts."""
    changes: list[str] = []
    if not report or not isinstance(report, dict):
        return changes

    has_trades = "trades" in report and report["trades"] is not None
    trades = parse_trades(report["trades"]) if "trades" in report else None

    if report.get("currency"):
        target["currency"] = report["currency"]
        changes.append("report.currency")
    if report.get("settings"):
        target["settings"] = AttrDict(report["settings"]) if isinstance(report["settings"], dict) else report["settings"]
        changes.append("report.settings")
    if report.get("performance"):
        target["performance"] = (
            AttrDict(report["performance"]) if isinstance(report["performance"], dict) else report["performance"]
        )
        changes.append("report.perf")
    if "trades" in report:
        target["trades"] = trades
        changes.append("report.trades")

    history_keys = ("buyHold", "buyHoldPercent", "drawDown", "drawDownPercent", "equity", "equityPercent")
    history = target.setdefault("history", AttrDict())
    history_changed = False
    for k in history_keys:
        if isinstance(report.get(k), list):
            history[k] = report[k]
            history_changed = True
    if history_changed:
        changes.append("report.history")
    return changes


mergeStrategyReport = merge_strategy_report


def summarize_strategy_report(report: dict[str, Any]) -> StrategySummary:
    """Summarizes reported aggregates without inferring missing values or trade status."""

    def _finite(val: Any) -> int | float | None:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        if not math.isfinite(val):
            return None
        return val

    def _count(val: Any) -> int | None:
        n = _finite(val)
        if n is None:
            return None
        if isinstance(n, float) and not n.is_integer():
            return None
        i = int(n)
        return i if i >= 0 else None

    perf = report.get("performance") or {}
    all_perf = perf.get("all") if isinstance(perf, dict) else None
    all_dict = all_perf if isinstance(all_perf, dict) else {}

    closed_net_profit = _finite(all_dict.get("netProfit"))
    open_pnl = _finite(perf.get("openPL") if isinstance(perf, dict) else None)
    total_pnl = None
    if closed_net_profit is not None and open_pnl is not None:
        try:
            summed = float(closed_net_profit) + float(open_pnl)
            if math.isfinite(summed):
                total_pnl = int(summed) if summed.is_integer() and isinstance(closed_net_profit, int) and isinstance(open_pnl, int) else summed
        except OverflowError:
            total_pnl = None

    return AttrDict(
        {
            "currency": report.get("currency"),
            "tradeRecordCount": len(report.get("trades") or ()),
            "closedTradeCount": _count(all_dict.get("totalTrades")),
            "openTradeCount": _count(all_dict.get("totalOpenTrades")),
            "closedNetProfit": closed_net_profit,
            "openPnL": open_pnl,
            "totalPnL": total_pnl,
        }
    )


summarizeStrategyReport = summarize_strategy_report
