import copy
import math
import sys
import pytest

from tradingview._types import AttrDict
from tradingview.chart.strategy import mergeStrategyReport, summarizeStrategyReport


def empty():
    return AttrDict({"trades": [], "history": AttrDict(), "performance": AttrDict()})


def test_strategy_report_keeps_buy_and_hold_history_and_preserves_omitted_series():
    report = empty()
    assert mergeStrategyReport(report, {"buyHold": [1, 2], "buyHoldPercent": [0, 0.1]}) == [
        "report.history"
    ]
    mergeStrategyReport(report, {"equity": [10, 11]})
    mergeStrategyReport(report, {"buyHold": []})
    assert report["history"] == {"buyHold": [], "buyHoldPercent": [0, 0.1], "equity": [10, 11]}
    assert mergeStrategyReport(report, {"equity": None, "buyHold": "invalid"}) == []
    assert report["history"]["equity"] == [10, 11]


def test_strategy_report_uses_aggregate_counts():
    report = empty()
    mergeStrategyReport(
        report,
        {
            "currency": "USD",
            "performance": {"all": {"totalTrades": 2, "totalOpenTrades": 1, "netProfit": 12}, "openPL": -3},
            "trades": [
                {
                    "e": {"c": "Entry", "tp": "le", "p": 100, "tm": i * 1000},
                    "x": {"c": "", "p": 97, "tm": (i + 1) * 1000},
                    "q": 1,
                    "tp": {"v": -3, "p": -0.03},
                    "cp": {"v": 9, "p": 0.09},
                    "rn": {"v": 1, "p": 0.01},
                    "dd": {"v": 3, "p": 0.03},
                }
                for i in range(3)
            ],
        },
    )
    before = copy.deepcopy(report)
    assert summarizeStrategyReport(report) == {
        "currency": "USD",
        "tradeRecordCount": 3,
        "closedTradeCount": 2,
        "openTradeCount": 1,
        "closedNetProfit": 12,
        "openPnL": -3,
        "totalPnL": 9,
    }
    assert report == before


def test_strategy_report_does_not_invent_zero_counts_for_missing_or_invalid_aggregates():
    report = empty()
    s0 = summarizeStrategyReport(report)
    assert s0["tradeRecordCount"] == 0
    assert s0["closedTradeCount"] is None
    assert s0["openTradeCount"] is None
    assert s0["closedNetProfit"] is None
    assert s0["openPnL"] is None
    assert s0["totalPnL"] is None

    mergeStrategyReport(
        report,
        {"performance": {"all": {"totalTrades": -1, "totalOpenTrades": 0.5, "netProfit": 12}}},
    )
    s1 = summarizeStrategyReport(report)
    assert s1["closedTradeCount"] is None
    assert s1["openTradeCount"] is None
    assert s1["closedNetProfit"] == 12
    assert s1["totalPnL"] is None

    mergeStrategyReport(
        report,
        {"performance": {"all": {"totalTrades": 0, "totalOpenTrades": 0, "netProfit": 0}, "openPL": 0}},
    )
    s2 = summarizeStrategyReport(report)
    assert s2["closedTradeCount"] == 0
    assert s2["openTradeCount"] == 0
    assert s2["totalPnL"] == 0

    mergeStrategyReport(
        report,
        {"performance": {"all": {"netProfit": math.inf}, "openPL": math.nan}},
    )
    s3 = summarizeStrategyReport(report)
    assert s3["closedNetProfit"] is None
    assert s3["openPnL"] is None
    assert s3["totalPnL"] is None


def test_strategy_report_rejects_malformed_trade_lists_without_partial_overwrite():
    report = empty()
    mergeStrategyReport(report, {"currency": "USD", "performance": {"openPL": 2}, "equity": [100]})
    before = copy.deepcopy(report)
    for trades in [None, {}, "invalid", [None], [1], [[]]]:
        with pytest.raises(Exception, match="Strategy trades must be an array of records"):
            mergeStrategyReport(
                report,
                {"currency": "EUR", "performance": {"openPL": 9}, "trades": trades, "equity": [200]},
            )
        assert report == before
    assert mergeStrategyReport(report, {"trades": []}) == ["report.trades"]
    assert report["trades"] == []


def test_strategy_report_keeps_missing_pnl_unknown_and_rejects_overflowing_total():
    report = empty()
    mergeStrategyReport(report, {"performance": {"all": {"totalOpenTrades": 0, "netProfit": 2}}})
    assert summarizeStrategyReport(report)["totalPnL"] is None
    mergeStrategyReport(
        report,
        {"performance": {"all": {"netProfit": sys.float_info.max}, "openPL": sys.float_info.max}},
    )
    assert summarizeStrategyReport(report)["totalPnL"] is None
