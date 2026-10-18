import asyncio
import base64
import json
import zlib
from pathlib import Path
import pytest

from tradingview.client.client import TradingViewClient
from tradingview.chart.graphics import applyGraphicsCommands, parseGraphics
from tradingview.indicators.builtin_indicator import BuiltInIndicator
from tests.helpers.fake_server import FakeServer, until
from tests.helpers.indicators import makePine

COMPRESSED_FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "compressed-report.json").read_text(encoding="utf-8")
)


async def setup(options=None):
    opts = {"history": 10, **(options or {})}
    server = FakeServer(opts)
    client = TradingViewClient({"transport": server.transport})
    await client.ready
    chart = client.createChart()
    chart.setMarket("BINANCE:BTCEUR", {"count": 5})
    return server, client, chart, server.last


@pytest.mark.asyncio
async def test_study_creates_pine_study_names_plots_and_keeps_duplicates():
    server, client, chart, connection = await setup({"studyPlots": 3})
    pine = makePine()
    study = chart.createStudy(pine)
    events = []
    study.onAny(lambda event, *_: events.append(event))
    await until(lambda: study.isReady)

    assert connection.packets("create_study")[0]["p"] == [
        chart.id,
        study.id,
        "st1",
        "$prices",
        "Script@tv-scripting-101!",
        pine.toStudyInputs(),
    ]
    assert len(study.values) == 5
    assert study.values[-1] == {
        "$time": server.barTime(9),
        "Value": 9,
        "plot_1": 9.1,
        "Signal": 9.2,
    }
    assert events == ["loading", "update", "ready"]
    assert chart.studies == [study]
    await client.close()


@pytest.mark.asyncio
async def test_study_modifies_and_removes():
    _, client, chart, connection = await setup()
    study = chart.createStudy(BuiltInIndicator("Volume@tv-basicstudies-241"))
    updated = BuiltInIndicator("Volume@tv-basicstudies-241", {"length": 50})
    study.setIndicator(updated)
    assert connection.packets("modify_study")[0]["p"] == [
        chart.id,
        study.id,
        "st1",
        {"length": 50, "col_prev_close": False},
    ]
    assert study.indicator is updated
    with pytest.raises(Exception, match="PineIndicator"):
        study.setIndicator({})
    study.remove()
    study.remove()
    assert connection.packets("remove_study") == [{"m": "remove_study", "p": [chart.id, study.id]}]
    assert chart.studies == []
    with pytest.raises(Exception, match="PineIndicator"):
        chart.createStudy("STD;RSI")
    await client.close()


@pytest.mark.asyncio
async def test_study_formats_study_errors_with_context():
    _, client, chart, _ = await setup(
        {
            "studyError": {
                "error": "Invalid value of the '{argName}' argument ({value}) in the '{funName}' function.",
                "ctx": {"argName": "factor", "value": -1, "funName": "supertrend"},
            }
        }
    )
    study = chart.createStudy(makePine())
    fut = asyncio.get_running_loop().create_future()
    study.on("error", lambda err: fut.set_result(err) if not fut.done() else None)
    error = await fut
    assert error.code == "STUDY_ERROR"
    assert (
        error.message
        == "Study error: Invalid value of the 'factor' argument (-1) in the 'supertrend' function."
    )
    await client.close()


@pytest.mark.asyncio
async def test_study_reads_graphics_commands_and_positions_in_bars_back():
    server, client, chart, _ = await setup(
        {
            "studyNs": lambda: {
                "graphicsCmds": {
                    "create": {
                        "dwglabels": [
                            {
                                "data": [
                                    {
                                        "id": 1,
                                        "x": 0,
                                        "y": 10,
                                        "yl": "ab",
                                        "t": "Hi",
                                        "st": "lup",
                                        "ci": 1,
                                        "tci": 2,
                                        "sz": "small",
                                        "ta": "center",
                                        "tt": "tip",
                                    }
                                ]
                            }
                        ],
                        "dwglines": [
                            {
                                "data": [
                                    {
                                        "id": 2,
                                        "x1": 1,
                                        "y1": 1,
                                        "x2": 2,
                                        "y2": 2,
                                        "ex": "r",
                                        "st": "dsh",
                                        "ci": 3,
                                        "w": 1,
                                    }
                                ]
                            }
                        ],
                        "dwgboxes": [
                            {
                                "data": [
                                    {
                                        "id": 3,
                                        "x1": 0,
                                        "y1": 1,
                                        "x2": 2,
                                        "y2": 0,
                                        "c": 1,
                                        "bc": 2,
                                        "ex": "n",
                                        "st": "dot",
                                        "w": 2,
                                        "t": "Box",
                                        "ts": "auto",
                                        "tc": 3,
                                        "tva": "top",
                                        "tha": "left",
                                        "tw": "none",
                                    }
                                ]
                            }
                        ],
                        "dwgtables": [
                            {
                                "data": [
                                    {
                                        "id": 4,
                                        "pos": "top_right",
                                        "rows": 1,
                                        "cols": 2,
                                        "bgc": 1,
                                        "frmc": 2,
                                        "frmw": 1,
                                        "brdc": 3,
                                        "brdw": 1,
                                    }
                                ]
                            }
                        ],
                        "dwgtablecells": [
                            {
                                "data": [
                                    {
                                        "id": 5,
                                        "tid": 4,
                                        "row": 0,
                                        "col": 1,
                                        "t": "B",
                                        "w": 0,
                                        "h": 0,
                                        "tc": 1,
                                        "tha": "center",
                                        "tva": "center",
                                        "ts": "auto",
                                        "bgc": 2,
                                    },
                                    {
                                        "id": 6,
                                        "tid": 4,
                                        "row": 0,
                                        "col": 0,
                                        "t": "A",
                                        "w": 0,
                                        "h": 0,
                                        "tc": 1,
                                        "tha": "center",
                                        "tva": "center",
                                        "ts": "auto",
                                        "bgc": 2,
                                    },
                                ]
                            }
                        ],
                        "hhists": [
                            {
                                "data": [
                                    {
                                        "id": 7,
                                        "priceLow": 1,
                                        "priceHigh": 2,
                                        "firstBarTime": 0,
                                        "lastBarTime": 2,
                                        "rate": [1, 2],
                                    }
                                ]
                            }
                        ],
                        "horizlines": [
                            {
                                "data": [
                                    {
                                        "id": 8,
                                        "level": 5,
                                        "startIndex": 0,
                                        "endIndex": 1,
                                        "extendLeft": False,
                                        "extendRight": True,
                                    }
                                ]
                            }
                        ],
                        "polygons": [{"data": [{"id": 9, "points": [{"index": 1, "level": 3}]}]}],
                    }
                }
            }
        }
    )
    study = chart.createStudy(makePine())
    await until(lambda: study.isReady and len(chart.candles) == 5)
    graphics = study.graphics
    assert graphics["labels"] == [
        {
            "id": 1,
            "x": 4,
            "y": 10,
            "yLoc": "abovebar",
            "text": "Hi",
            "style": "label_up",
            "color": 1,
            "textColor": 2,
            "size": "small",
            "textAlign": "center",
            "toolTip": "tip",
        }
    ]
    assert graphics["lines"][0]["x1"] == 3
    assert graphics["lines"][0]["x2"] == 2
    assert graphics["lines"][0]["extend"] == "right"
    assert graphics["lines"][0]["style"] == "dashed"
    assert graphics["boxes"][0]["x1"] == 4
    assert graphics["boxes"][0]["x2"] == 2
    assert graphics["boxes"][0]["extend"] == "none"
    assert graphics["boxes"][0]["style"] == "dotted"
    assert graphics["boxes"][0]["text"] == "Box"
    assert graphics["tables"][0]["position"] == "top_right"
    assert graphics["tables"][0]["columns"] == 2
    assert [[cell["text"] for cell in row] for row in graphics["tables"][0]["cells"]] == [["A", "B"]]
    assert graphics["horizHists"][0]["firstBarTime"] == 4
    assert graphics["horizHists"][0]["lastBarTime"] == 2
    assert graphics["horizHists"][0]["rate"] == [1, 2]
    assert graphics["horizLines"][0]["startIndex"] == 4
    assert graphics["horizLines"][0]["endIndex"] == 3
    assert graphics["horizLines"][0]["extendRight"] is True
    assert graphics["polygons"][0]["points"] == [{"index": 3, "level": 3}]
    assert "dwglabels" in graphics["raw"]
    assert server.options["history"] == 10
    await client.close()


def test_study_applies_erase_commands():
    raw = {}
    applyGraphicsCommands(
        raw,
        {
            "create": {
                "dwglabels": [{"data": [{"id": 1}, {"id": 2}]}],
                "dwglines": [{"data": [{"id": 3}]}],
            }
        },
    )
    applyGraphicsCommands(
        raw,
        {"erase": [{"action": "one", "type": "dwglabels", "id": 1}, {"action": "one", "id": 99}]},
    )
    assert list(raw["dwglabels"].keys()) == ["2"]
    applyGraphicsCommands(raw, {"erase": [{"action": "all", "type": "dwglines"}]})
    assert "dwglines" not in raw
    applyGraphicsCommands(raw, {"erase": [{"action": "all"}]})
    assert raw == {"dwglabels": {}}
    assert parseGraphics(raw)["labels"] == []


@pytest.mark.asyncio
async def test_study_decodes_plain_and_compressed_strategy_reports():
    plain_report = {"report": {"currency": "USD", "performance": {"all": {"totalTrades": 1}}}}
    for ns in [{"data": plain_report}, {"dataCompressed": COMPRESSED_FIXTURE["zipDeflated"]}]:
        _, client, chart, _ = await setup({"studyNs": lambda *_, ns=ns: ns})
        study = chart.createStudy(makePine().setType("StrategyScript@tv-scripting-101!"))
        changes = []
        study.on("update", lambda c, changes=changes: changes.append(c))
        await until(lambda: study.isReady)
        if "data" in ns:
            assert study.strategyReport["currency"] == "USD"
            assert study.strategyReport["performance"]["all"]["totalTrades"] == 1
            assert changes[0] == ["plots", "report.currency", "report.perf"]
        else:
            report = study.strategyReport
            assert report["currency"] == "EUR"
            assert report["settings"]["dateRange"]["backtest"] == {"from": 1, "to": 2}
            assert [t["entry"]["type"] for t in report["trades"]] == ["short", "long"]
            assert report["trades"][0]["entry"]["name"] == "Short"
            assert report["trades"][0]["entry"]["value"] == 110
            assert report["trades"][0]["exit"]["name"] == ""
            assert report["trades"][0]["exit"]["value"] == 105
            assert report["trades"][0]["quantity"] == 2
            assert report["trades"][0]["profit"] == {"v": 10, "p": 0.05}
            assert report["history"]["equity"] == [1, 2]
            assert changes[0] == [
                "plots",
                "report.currency",
                "report.settings",
                "report.perf",
                "report.trades",
                "report.history",
            ]
        await client.close()


@pytest.mark.asyncio
async def test_study_decodes_unpadded_zlib_report():
    payload = {
        "report": {
            "currency": "USD",
            "buyHold": [100, 102],
            "buyHoldPercent": [0, 0.02],
            "performance": {"all": {"totalTrades": 2, "totalOpenTrades": 1, "netProfit": 12}, "openPL": -3},
        }
    }
    data_compressed = (
        base64.b64encode(zlib.compress(json.dumps(payload).encode("utf-8")))
        .decode("ascii")
        .rstrip("=")
    )
    _, client, chart, _ = await setup({"studyNs": lambda *_: {"dataCompressed": data_compressed}})
    study = chart.createStudy(makePine())
    await until(lambda: study.isReady)
    assert study.strategyReport["history"] == {"buyHold": [100, 102], "buyHoldPercent": [0, 0.02]}
    assert study.strategyReport["performance"] == payload["report"]["performance"]
    await client.close()


@pytest.mark.asyncio
async def test_study_reports_undecodable_strategy_reports_as_parse_error():
    _, client, chart, _ = await setup({"studyNs": lambda *_: {"dataCompressed": "bm90IGpzb24"}})
    study = chart.createStudy(makePine())
    fut = asyncio.get_running_loop().create_future()
    study.on("error", lambda err: fut.set_result(err) if not fut.done() else None)
    error = await fut
    assert error.code == "PARSE_ERROR"
    await client.close()


@pytest.mark.asyncio
async def test_study_emits_parse_error_for_malformed_trades_without_mutating():
    payload = {"report": {"currency": "EUR", "trades": [None]}}
    compressed_payload = base64.b64encode(
        zlib.compress(json.dumps(payload).encode("utf-8"))
    ).decode("ascii")
    for ns in [{"data": payload}, {"dataCompressed": compressed_payload}]:
        _, client, chart, _ = await setup({"studyNs": lambda *_, ns=ns: ns})
        try:
            study = chart.createStudy(makePine())
            errors = []
            study.on("error", lambda err, errors=errors: errors.append(err))
            await until(lambda: study.isReady)
            assert len(errors) == 1
            assert errors[0].code == "PARSE_ERROR"
            assert study.strategyReport.get("currency") is None
            assert study.strategyReport["trades"] == []
        finally:
            await client.close()
