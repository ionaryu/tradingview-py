import json
from pathlib import Path
import pytest

from tradingview.client.client import TradingViewClient
from tradingview.indicators.builtin_indicator import BuiltInIndicator
from tradingview.protocol.framing import decodeFrames
from tests.helpers.fake_server import FakeServer, flush, until

LIVE_FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "live-session.json").read_text(encoding="utf-8")
)


async def setup(options=None):
    server = FakeServer(options or {})
    client = TradingViewClient({"transport": server.transport})
    await client.ready
    return server, client, server.last


@pytest.mark.asyncio
async def test_chart_session_creates_session_resolves_symbol_and_loads_candles():
    server, client, connection = await setup({"history": 50})
    chart = client.createChart()
    events = []
    chart.onAny(lambda event, *_: events.append(event))
    chart.setMarket("BINANCE:BTCEUR", {"timeframe": "240", "count": 3})
    await until(lambda: "seriesCompleted" in events)

    assert connection.packets("chart_create_session")[0]["p"] == [chart.id]
    assert connection.packets("resolve_symbol")[0]["p"] == [
        chart.id,
        "ser_1",
        '={"symbol":"BINANCE:BTCEUR","adjustment":"splits"}',
    ]
    assert connection.packets("create_series")[0]["p"] == [
        chart.id,
        "$prices",
        "s1",
        "ser_1",
        "240",
        3,
    ]
    assert chart.symbolInfo["series_id"] == "ser_1"
    assert chart.symbolInfo["full_name"] == "BINANCE:BTCEUR"
    assert [c["time"] for c in chart.candles] == [
        server.barTime(47),
        server.barTime(48),
        server.barTime(49),
    ]
    assert chart.lastCandle == {
        "time": server.barTime(49),
        "open": 148,
        "high": 151,
        "low": 146,
        "close": 149,
        "volume": 59,
    }
    assert events == ["symbolLoaded", "seriesLoading", "update", "seriesCompleted"]
    assert chart.seriesId == "ser_1"
    assert chart.timeframe == "240"
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_encodes_market_options_custom_chart_types_and_ranges():
    _, client, connection = await setup()
    chart = client.createChart()
    chart.setMarket(
        "CME:ES1!",
        {
            "timeframe": "D",
            "count": 10,
            "to": 1_700_000_000,
            "adjustment": "dividends",
            "backAdjustment": True,
            "session": "extended",
            "currency": "EUR",
            "type": "Renko",
            "inputs": {"boxSize": 3, "style": "ATR"},
        },
    )
    init = connection.packets("resolve_symbol")[0]
    assert json.loads(init["p"][2][1:]) == {
        "symbol": {
            "symbol": "CME:ES1!",
            "adjustment": "dividends",
            "backadjustment": "default",
            "session": "extended",
            "currency-id": "EUR",
        },
        "type": "BarSetRenko@tv-prostudies-40!",
        "inputs": {"boxSize": 3, "style": "ATR"},
    }
    assert connection.packets("create_series")[0]["p"][5] == ["bar_count", 1_700_000_000, 10]
    with pytest.raises(Exception, match="Unknown chart type"):
        chart.setMarket("X", {"type": "Nope"})
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_modifies_series_on_later_calls():
    _, client, connection = await setup()
    chart = client.createChart()
    with pytest.raises(Exception) as exc_info:
        chart.setTimeframe("15")
    assert exc_info.value.code == "INVALID_STATE"
    chart.setMarket("BINANCE:BTCEUR")
    chart.setMarket("BINANCE:ETHEUR", {"timeframe": "60", "type": "HeikinAshi"})
    chart.setTimeframe("15")
    assert [p["p"] for p in connection.packets("modify_series")] == [
        [chart.id, "$prices", "s2", "ser_2", "60", ""],
        [chart.id, "$prices", "s3", "ser_2", "15", ""],
    ]
    assert json.loads(connection.packets("resolve_symbol")[1]["p"][2][1:]) == {
        "symbol": {"symbol": "BINANCE:ETHEUR", "adjustment": "splits"},
        "type": "BarSetHeikenAshi@tv-basicstudies-60!",
        "inputs": {},
    }
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_fetches_more_history_and_switches_timezone():
    _, client, connection = await setup({"history": 20})
    chart = client.createChart()
    completions = []
    chart.on("seriesCompleted", lambda info: completions.append(info.get("dataCompleted")))
    chart.setTimezone("Europe/Paris")
    chart.setMarket("BINANCE:BTCEUR", {"count": 5})
    await until(lambda: len(completions) == 1)
    chart.fetchMore(30)
    await until(lambda: len(completions) == 2)
    assert connection.packets("switch_timezone")[0]["p"] == [chart.id, "Europe/Paris"]
    assert connection.packets("request_more_data")[0]["p"] == [chart.id, "$prices", 30]
    assert len(chart.candles) == 20
    assert completions == [None, "end"]
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_emits_typed_errors():
    _, client, connection = await setup()
    chart = client.createChart()
    errors = []
    chart.on("error", lambda error: errors.append(f"{error.code}: {error.message}"))
    chart.setMarket("XXXXX")
    await until(lambda: len(errors) == 1)
    connection.push(
        {"m": "series_error", "p": [chart.id, "$prices", "s1", "custom_resolution"]},
        {"m": "critical_error", "p": [chart.id, "invalid timezone", "method: switch_timezone"]},
    )
    assert errors == [
        "SYMBOL_ERROR: (ser_1) Symbol error: invalid symbol",
        "SERIES_ERROR: Series error: custom_resolution",
        "CRITICAL_ERROR: Critical error: invalid timezone",
    ]
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_runs_replay_mode():
    _, client, connection = await setup({"replaySteps": 2})
    chart = client.createChart()
    with pytest.raises(Exception) as exc_info:
        await chart.replayStep()
    assert exc_info.value.code == "INVALID_STATE"

    events = []
    chart.onAny(
        lambda event, *args: events.append([event, *args])
        if str(event).startswith("replay")
        else None
    )
    chart.setMarket("BINANCE:BTCEUR", {"timeframe": "D", "replay": 1_700_000_000, "count": 1})
    assert chart.isReplay is True

    assert connection.packets("replay_create_session")[0]["p"] == [chart.replayId]
    assert connection.packets("replay_add_series")[0]["p"] == [
        chart.replayId,
        "req_replay_addseries",
        '={"symbol":"BINANCE:BTCEUR","adjustment":"splits"}',
        "D",
    ]
    assert connection.packets("replay_reset")[0]["p"] == [
        chart.replayId,
        "req_replay_reset",
        1_700_000_000,
    ]
    assert json.loads(connection.packets("resolve_symbol")[0]["p"][2][1:]) == {
        "symbol": {"symbol": "BINANCE:BTCEUR", "adjustment": "splits"},
        "replay": chart.replayId,
    }

    await chart.replayStep(1)
    await chart.replayStart(200)
    await chart.replayStop()
    await chart.replayStep(1)
    await flush()
    assert [e[0] for e in events] == [
        "replayLoaded",
        "replayPoint",
        "replayResolution",
        "replayPoint",
        "replayPoint",
        "replayEnd",
    ]
    assert events[2] == ["replayResolution", "1D", "1S"]
    assert connection.packets("replay_start")[0]["p"][2] == 200

    chart.setMarket("BINANCE:BTCEUR")
    assert chart.isReplay is False
    assert len(connection.packets("replay_delete_session")) == 1
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_rejects_pending_replay_requests_when_deleted():
    server, client, connection = await setup()
    server.on("replay_step", lambda *_: True)
    chart = client.createChart()
    chart.setMarket("BINANCE:BTCEUR", {"replay": 1_700_000_000})
    step = chart.replayStep()
    chart.delete()
    chart.delete()
    with pytest.raises(Exception) as exc_info:
        await step
    assert exc_info.value.code == "INVALID_STATE"
    assert len(connection.packets("chart_delete_session")) == 1
    assert len(connection.packets("replay_delete_session")) == 1
    assert chart.isDeleted is True
    with pytest.raises(Exception, match="deleted"):
        chart.setMarket("X")
    await client.close()


@pytest.mark.asyncio
async def test_chart_session_reports_disconnected_when_connection_drops():
    _, client, connection = await setup()
    chart = client.createChart()
    chart.setMarket("BINANCE:BTCEUR")
    study = chart.createStudy(BuiltInIndicator("Volume@tv-basicstudies-241"))
    errors = []
    chart.on("error", lambda e: errors.append(f"chart:{e.code}"))
    study.on("error", lambda e: errors.append(f"study:{e.code}"))
    connection.drop()
    assert sorted(errors) == ["chart:DISCONNECTED", "study:DISCONNECTED"]
    assert chart.isDeleted is True
    assert study.isRemoved is True


@pytest.mark.asyncio
async def test_chart_session_parses_captured_live_session():
    _, client, connection = await setup()
    chart = client.createChart()
    study = chart.createStudy(BuiltInIndicator("Volume@tv-basicstudies-241"))
    errors = []
    chart.on("error", lambda error: errors.append(error.message))
    ready = False

    def on_ready():
        nonlocal ready
        ready = True

    study.on("ready", on_ready)

    for message in LIVE_FIXTURE["messages"]:
        for frame in decodeFrames(message):
            if frame["type"] != "packet":
                continue
            raw_json = (
                json.dumps(frame["packet"])
                .replace("cs_fixture", chart.id)
                .replace("st_fixture", study.id)
            )
            connection.push(json.loads(raw_json))

    assert chart.symbolInfo["full_name"] == "BINANCE:BTCEUR"
    assert chart.symbolInfo["currency_code"] == "EUR"
    assert chart.symbolInfo["series_id"] == "ser_1"
    assert len(chart.candles) == 3
    for candle in chart.candles:
        assert candle["high"] >= max(candle["open"], candle["close"])
        assert candle["low"] <= min(candle["open"], candle["close"])
    assert len(study.values) > 3
    assert list(study.values[0].keys()) == ["$time", "plot_0", "plot_1", "plot_2"]
    assert ready is True
    assert errors == ["(ser_2) Symbol error: invalid symbol"]
    await client.close()


@pytest.mark.asyncio
async def test_intentional_close_does_not_report_errors():
    _, client, _ = await setup()
    chart = client.createChart()
    chart.setMarket("BINANCE:BTCEUR")
    study = chart.createStudy(BuiltInIndicator("Volume@tv-basicstudies-241"))
    quotes = client.createQuoteSession()
    sub = quotes.subscribe("BINANCE:BTCEUR")
    errors = []
    for emitter in [chart, study, quotes, sub]:
        emitter.on("error", lambda e: errors.append(e))
    await client.close()
    assert errors == []
    assert chart.isDeleted and study.isRemoved and quotes.isDeleted and sub.isClosed
