import asyncio
from datetime import datetime, timezone
import json
import pytest

from tradingview._types import AbortController, AttrDict, FetchHeaders, FetchResponse
from tradingview.client.client import TradingViewClient
from tradingview.data import (
    TradingViewProvider,
    getCandles,
    getIndicatorData,
    getQuote,
    getQuotes,
    getSymbolInfo,
    watchCandles,
    watchIndicator,
    watchQuotes,
)
from tradingview.indicators.builtin_indicator import BuiltInIndicator
from tests.helpers.fake_server import FakeServer, flush, until
from tests.helpers.indicators import makePine


def fake(options=None):
    server = FakeServer(options or {})
    return server, {"transport": server.transport}


@pytest.mark.asyncio
async def test_get_candles_returns_most_recent_oldest_first_and_closes():
    server, client_options = fake({"history": 500})
    candles = await getCandles(
        {"symbol": "BINANCE:BTCUSDT", "timeframe": "60", "count": 3, "clientOptions": client_options}
    )
    assert [c["close"] for c in candles] == [597, 598, 599]
    assert candles[0] == {
        "time": server.barTime(497),
        "open": 596,
        "high": 599,
        "low": 594,
        "close": 597,
        "volume": 507,
    }
    connection = server.last
    assert connection.packets("create_series")[0]["p"][4:] == ["60", 3]
    assert len(connection.packets("chart_delete_session")) == 1
    assert connection.closed is True


@pytest.mark.asyncio
async def test_get_candles_accepts_symbol_with_defaults():
    server, client_options = fake()
    client = TradingViewClient(client_options)
    candles = await getCandles({"symbol": "BINANCE:BTCUSDT", "client": client})
    assert len(candles) == 100
    assert server.last.packets("create_series")[0]["p"][4:] == ["D", 100]
    assert client.isClosed is False
    assert len(server.last.packets("chart_delete_session")) == 1
    await client.close()


@pytest.mark.asyncio
async def test_get_candles_accepts_alternate_provider_and_stops_worker():
    snapshot = [AttrDict({"time": 1, "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 4})]
    stop_calls = 0

    async def stop():
        nonlocal stop_calls
        stop_calls += 1

    class CustomProvider:
        async def watchCandles(self, _query, handlers):
            handlers.onData(snapshot)
            return AttrDict({"latest": snapshot, "stop": stop})

    provider = CustomProvider()
    assert await getCandles({"symbol": "CUSTOM:ASSET"}, provider) == snapshot
    assert stop_calls == 1

    seen = []
    worker = await watchCandles(
        {"symbol": "CUSTOM:ASSET"},
        {"onData": lambda candles: seen.append(candles[0]["close"])},
        provider,
    )
    assert worker.latest == snapshot
    assert seen == [2.5]
    await worker.stop()
    assert stop_calls == 2

    server, client_options = fake()
    tv_provider = TradingViewProvider({"clientOptions": client_options})
    candles = await getCandles({"symbol": "BINANCE:BTCUSDT", "count": 2}, tv_provider)
    assert len(candles) == 2
    assert server.last.closed is True


@pytest.mark.asyncio
async def test_get_candles_loads_deep_history_in_batches():
    server, client_options = fake({"history": 12_000, "batchLimit": 5_000})
    candles = await getCandles(
        {"symbol": "BINANCE:BTCUSDT", "count": 11_000, "clientOptions": client_options}
    )
    assert len(candles) == 11_000
    assert candles[0]["time"] == server.barTime(1_000)
    assert server.last.packets("create_series")[0]["p"][5] == 5_000
    assert [p["p"][2] for p in server.last.packets("request_more_data")] == [5_000, 1_000]


@pytest.mark.asyncio
async def test_get_candles_stops_when_server_has_no_more_history():
    server, client_options = fake({"history": 120, "batchLimit": 50, "endReason": "limit"})
    candles = await getCandles(
        {"symbol": "BINANCE:BTCUSDT", "count": 1_000, "clientOptions": client_options}
    )
    assert len(candles) == 120
    assert len(server.last.packets("request_more_data")) == 2


@pytest.mark.asyncio
async def test_get_candles_loads_from_to_range_accepting_dates_and_unix_seconds():
    server, client_options = fake({"history": 1_000, "batchLimit": 100, "step": 3_600})
    from_dt = datetime.fromtimestamp(server.barTime(700), tz=timezone.utc)
    to_ts = server.barTime(750)
    candles = await getCandles(
        {
            "symbol": "BINANCE:BTCUSDT",
            "timeframe": "60",
            "from": from_dt,
            "to": to_ts,
            "clientOptions": client_options,
        }
    )
    assert candles[0]["time"] == server.barTime(700)
    assert candles[-1]["time"] == to_ts
    assert len(candles) == 51
    create = server.last.packets("create_series")[0]
    assert create["p"][5][0] == "bar_count"
    assert create["p"][5][1] == to_ts
    assert len(server.last.packets("request_more_data")) > 0


@pytest.mark.asyncio
async def test_get_candles_passes_chart_options():
    server, client_options = fake()
    await getCandles(
        {
            "symbol": "NASDAQ:AAPL",
            "chartType": "HeikinAshi",
            "chartInputs": {"foo": 1},
            "currency": "EUR",
            "session": "extended",
            "adjustment": "dividends",
            "backAdjustment": True,
            "timezone": "Europe/Paris",
            "count": 2,
            "clientOptions": client_options,
        }
    )
    connection = server.last
    assert connection.packets("switch_timezone")[0]["p"][1] == "Europe/Paris"
    assert json.loads(connection.packets("resolve_symbol")[0]["p"][2][1:]) == {
        "symbol": {
            "symbol": "NASDAQ:AAPL",
            "adjustment": "dividends",
            "backadjustment": "default",
            "session": "extended",
            "currency-id": "EUR",
        },
        "type": "BarSetHeikenAshi@tv-basicstudies-60!",
        "inputs": {"foo": 1},
    }


@pytest.mark.asyncio
async def test_get_candles_rejects_invalid_queries_before_connecting():
    server, client_options = fake()
    with pytest.raises(Exception) as e1:
        await getCandles({"symbol": "", "clientOptions": client_options})
    assert e1.value.code == "INVALID_ARGUMENT"
    with pytest.raises(Exception, match="count"):
        await getCandles({"symbol": "A", "count": 0, "clientOptions": client_options})
    with pytest.raises(Exception, match="from"):
        await getCandles({"symbol": "A", "from": 10, "to": 5, "clientOptions": client_options})
    with pytest.raises(Exception, match="timeoutMs"):
        await getCandles({"symbol": "A", "timeoutMs": -1, "clientOptions": client_options})
    assert len(server.connections) == 0


@pytest.mark.asyncio
async def test_get_candles_rejects_symbol_errors_and_empty_results():
    _, client_options = fake()
    with pytest.raises(Exception) as e1:
        await getCandles({"symbol": "XXXXX", "clientOptions": client_options})
    assert e1.value.code == "SYMBOL_ERROR"

    _, empty_options = fake({"history": 0, "endReason": "limit"})
    with pytest.raises(Exception) as e2:
        await getCandles({"symbol": "A", "clientOptions": empty_options})
    assert e2.value.code == "NO_DATA"
    assert "access limit" in e2.value.message


@pytest.mark.asyncio
async def test_get_candles_timeout_abort_disconnect_and_closed_client():
    server, client_options = fake()
    server.respond = False
    with pytest.raises(Exception) as e_to:
        await getCandles({"symbol": "A", "timeoutMs": 20, "clientOptions": client_options})
    assert e_to.value.code == "TIMEOUT"
    assert server.last.closed is True

    server2, client_options2 = fake()
    server2.respond = False
    controller = AbortController()
    pending = getCandles({"symbol": "A", "signal": controller.signal, "clientOptions": client_options2})
    controller.abort(RuntimeError("user cancelled"))
    with pytest.raises(Exception) as e_ab:
        await pending
    assert e_ab.value.code == "ABORTED"
    assert e_ab.value.message == "user cancelled"
    assert server2.last.closed is True
    with pytest.raises(Exception) as e_ab2:
        await getCandles({"symbol": "A", "signal": controller.signal, "clientOptions": client_options2})
    assert e_ab2.value.code == "ABORTED"
    assert len(server2.connections) == 1

    server3, client_options3 = fake()
    server3.respond = False
    pending3 = getCandles({"symbol": "A", "clientOptions": client_options3})
    await until(lambda: len(server3.connections) > 0 and server3.connections[0].is_open)
    server3.last.drop()
    with pytest.raises(Exception) as e_dc:
        await pending3
    assert e_dc.value.code == "DISCONNECTED"

    _, client_options4 = fake()
    client = TradingViewClient(client_options4)
    await client.close()
    with pytest.raises(Exception) as e_st:
        await getCandles({"symbol": "A", "client": client})
    assert e_st.value.code == "INVALID_STATE"


@pytest.mark.asyncio
async def test_watch_candles_streams_updates_and_stops_idempotently():
    server, client_options = fake({"history": 10})
    snapshots = []
    watcher = await watchCandles(
        {"symbol": "BINANCE:BTCUSDT", "count": 3, "clientOptions": client_options},
        {"onData": lambda candles: snapshots.append([c["close"] for c in candles])},
    )
    assert watcher.isActive is True
    assert [c["close"] for c in watcher.latest] == [107, 108, 109]
    assert isinstance(watcher.latest, tuple)
    assert watcher.symbolInfo["full_name"] == "BINANCE:BTCUSDT"

    chart_id = server.last.packets("chart_create_session")[0]["p"][0]
    server.last.push(
        {
            "m": "du",
            "p": [
                chart_id,
                {"$prices": {"s": [{"i": 10, "v": [server.barTime(9) + 86_400, 1, 2, 0, 1.5, 1]}]}},
            ],
        }
    )
    assert snapshots == [[107, 108, 109], [108, 109, 1.5]]

    await asyncio.gather(watcher.stop(), watcher.stop())
    await watcher.closed
    assert watcher.isActive is False
    server.last.push({"m": "du", "p": [chart_id, {"$prices": {"s": []}}]})
    assert len(snapshots) == 2
    assert server.last.closed is True


@pytest.mark.asyncio
async def test_watch_candles_error_handling_and_shared_client():
    server, client_options = fake()
    errors = []
    watcher = await watchCandles(
        {"symbol": "A", "clientOptions": client_options},
        {"onData": lambda *_: None, "onError": lambda e: errors.append(e.code)},
    )
    server.last.drop()
    await watcher.closed
    assert errors == ["DISCONNECTED"]
    assert watcher.isActive is False

    server2, client_options2 = fake()
    errors2 = []

    def bad_on_data(*_):
        raise RuntimeError("consumer bug")

    watcher2 = await watchCandles(
        {"symbol": "A", "clientOptions": client_options2},
        {"onData": bad_on_data, "onError": lambda e: errors2.append(e.code)},
    )
    assert errors2 == ["CALLBACK_ERROR"]
    assert watcher2.isActive is True
    await watcher2.stop()
    assert server2.last.closed is True

    server3, client_options3 = fake()
    controller = AbortController()
    errors3 = []
    watcher3 = await watchCandles(
        {"symbol": "A", "signal": controller.signal, "clientOptions": client_options3},
        {"onData": lambda *_: None, "onError": lambda e: errors3.append(e.code)},
    )
    controller.abort()
    await watcher3.closed
    assert errors3 == ["ABORTED"]
    assert server3.last.closed is True

    server4, client_options4 = fake()
    with pytest.raises(Exception) as e_sym:
        await watchCandles({"symbol": "XXXXX", "clientOptions": client_options4}, {"onData": lambda *_: None})
    assert e_sym.value.code == "SYMBOL_ERROR"
    assert server4.last.closed is True
    with pytest.raises(Exception, match="onData"):
        await watchCandles({"symbol": "A", "clientOptions": client_options4}, {})
    server4.respond = False
    with pytest.raises(Exception) as e_to:
        await watchCandles(
            {"symbol": "A", "timeoutMs": 10, "clientOptions": client_options4},
            {"onData": lambda *_: None},
        )
    assert e_to.value.code == "TIMEOUT"

    server5, client_options5 = fake()
    client = TradingViewClient(client_options5)
    a = await watchCandles({"symbol": "A", "client": client}, {"onData": lambda *_: None})
    b = await watchCandles({"symbol": "B", "client": client}, {"onData": lambda *_: None})
    await a.stop()
    await b.stop()
    assert len(server5.connections) == 1
    assert len(server5.last.packets("chart_delete_session")) == 2
    assert client.isClosed is False
    await client.close()


@pytest.mark.asyncio
async def test_quotes_high_level_api():
    server, client_options = fake()
    q = await getQuote({"symbol": "BINANCE:BTCUSDT", "fields": "price", "clientOptions": client_options})
    assert q["lp"] == 100
    assert server.last.packets("quote_set_fields")[0]["p"][1:] == ["lp"]
    assert server.last.closed is True

    quotes = await getQuotes({"symbols": ["A", "B", "A"], "clientOptions": client_options})
    assert list(quotes.keys()) == ["A", "B"]
    assert len(server.last.packets("quote_delete_session")) == 1

    with pytest.raises(Exception) as e_qe:
        await getQuote({"symbol": "XXXXX", "clientOptions": client_options})
    assert e_qe.value.code == "QUOTE_ERROR"
    with pytest.raises(Exception) as e_ia:
        await getQuotes({"symbols": [], "clientOptions": client_options})
    assert e_ia.value.code == "INVALID_ARGUMENT"

    server2, client_options2 = fake()
    seen = []
    errors = []
    watcher = await watchQuotes(
        {"symbols": ["A", "XXXXX"], "clientOptions": client_options2},
        {
            "onData": lambda symbol, quote, *_: seen.append(f"{symbol}:{quote['lp']}"),
            "onError": lambda e: errors.append(e.code),
        },
    )
    assert seen == ["A:100"]
    assert errors == ["QUOTE_ERROR"]
    assert list(watcher.latest.keys()) == ["A"]
    session_id = server2.last.packets("quote_create_session")[0]["p"][0]
    key = server2.last.packets("quote_add_symbols")[0]["p"][1]
    server2.last.push({"m": "qsd", "p": [session_id, {"n": key, "s": "ok", "v": {"lp": 101}}]})
    assert seen == ["A:100", "A:101"]
    await watcher.stop()
    assert server2.last.closed is True

    with pytest.raises(Exception) as e_all_fail:
        await watchQuotes({"symbols": ["XXXXX"], "clientOptions": client_options2}, {"onData": lambda *_: None})
    assert e_all_fail.value.code == "QUOTE_ERROR"


@pytest.mark.asyncio
async def test_get_symbol_info():
    server, client_options = fake()
    info = await getSymbolInfo({"symbol": "NASDAQ:AAPL", "clientOptions": client_options})
    assert info["full_name"] == "NASDAQ:AAPL"
    assert info["currency_code"] == "EUR"
    assert info["series_id"] == "ser_1"
    assert server.last.closed is True
    with pytest.raises(Exception) as exc_info:
        await getSymbolInfo({"symbol": "XXXXX", "clientOptions": client_options})
    assert exc_info.value.code == "SYMBOL_ERROR"


@pytest.mark.asyncio
async def test_indicator_data_high_level_api():
    server, client_options = fake({"history": 20, "studyPlots": 2})
    data = await getIndicatorData(
        {
            "symbol": "A",
            "indicator": "Volume@tv-basicstudies-241",
            "inputs": {"length": 5},
            "count": 4,
            "clientOptions": client_options,
        }
    )
    assert server.last.packets("create_study")[0]["p"][4] == "Volume@tv-basicstudies-241"
    assert server.last.packets("create_study")[0]["p"][5] == {"length": 5, "col_prev_close": False}
    assert len(data["candles"]) == 4
    assert data["values"][-1] == {"$time": server.barTime(19), "plot_0": 19, "plot_1": 19.1}
    assert isinstance(data["indicator"], BuiltInIndicator)
    assert server.last.closed is True

    server2, client_options2 = fake(
        {
            "history": 10,
            "studyNs": lambda *_: {"data": {"report": {"performance": {"all": {"totalTrades": 3}}}}},
        }
    )
    pine = makePine()
    fetch_calls = []

    async def mock_fetch(url, init=None):
        fetch_calls.append((url, init))
        return FetchResponse(
            status=200,
            headers=FetchHeaders(),
            body=json.dumps(
                {
                    "success": True,
                    "result": {
                        "ilTemplate": pine.script,
                        "metaInfo": {
                            "scriptIdPart": "PUB;test",
                            "description": "Test",
                            "shortDescription": "T",
                            "pine": {"version": "3.0"},
                            "inputs": [{"id": "in_0", "name": "Length", "defval": 14, "type": "integer"}],
                            "styles": {"plot_0": {"title": "Value"}},
                            "plots": [],
                        },
                    },
                }
            ),
        )

    data2 = await getIndicatorData(
        {
            "symbol": "A",
            "indicator": "PUB;test",
            "inputs": {"Length": 30},
            "credentials": {"session": "s"},
            "clientOptions": {**client_options2, "authToken": "tok", "fetch": mock_fetch},
        }
    )
    assert fetch_calls[0][0] == "https://pine-facade.tradingview.com/pine-facade/translate/PUB;test/last"
    assert fetch_calls[0][1]["headers"]["cookie"] == "sessionid=s"
    assert server2.last.packets("create_study")[0]["p"][5]["in_0"] == {
        "v": 30,
        "f": False,
        "t": "integer",
    }
    assert data2["values"][-1]["Value"] == 9
    assert data2["strategyReport"]["performance"]["all"]["totalTrades"] == 3

    server3, client_options3 = fake({"history": 300, "batchLimit": 100})
    pine3 = makePine()
    data3 = await getIndicatorData(
        {"symbol": "A", "indicator": pine3, "inputs": {"length": 50}, "count": 250, "clientOptions": client_options3}
    )
    assert pine3.inputs["in_0"]["value"] == 14
    assert len(data3["candles"]) == 250
    assert len(data3["values"]) == 250
    assert len(server3.last.packets("request_more_data")) == 2

    _, err_options = fake({"studyError": "study not auth"})
    with pytest.raises(Exception) as e_se:
        await getIndicatorData({"symbol": "A", "indicator": makePine(), "clientOptions": err_options})
    assert e_se.value.code == "STUDY_ERROR"
    assert e_se.value.message == "Study error: study not auth"
    with pytest.raises(Exception) as e_ia:
        await getIndicatorData({"symbol": "A", "indicator": "", "clientOptions": err_options})
    assert e_ia.value.code == "INVALID_ARGUMENT"

    async def f_nf(*_):
        return FetchResponse(
            status=200,
            headers=FetchHeaders(),
            body=json.dumps({"success": False, "reason": "nope"}),
        )

    with pytest.raises(Exception) as e_nf:
        await getIndicatorData(
            {"symbol": "A", "indicator": "STD;Nope", "clientOptions": {**err_options, "fetch": f_nf}}
        )
    assert e_nf.value.code == "NOT_FOUND"

    server4, client_options4 = fake({"history": 10})
    values = []
    watcher = await watchIndicator(
        {"symbol": "A", "indicator": makePine(), "count": 5, "clientOptions": client_options4},
        {"onData": lambda d: values.append(d["values"][-1]["Value"])},
    )
    chart_id = server4.last.packets("chart_create_session")[0]["p"][0]
    study_id = server4.last.packets("create_study")[0]["p"][1]
    server4.last.push(
        {
            "m": "du",
            "p": [chart_id, {study_id: {"st": [{"i": 9, "v": [server4.barTime(9), 42]}], "ns": {"d": ""}}}],
        }
    )
    await flush()
    assert values == [9, 42]
    assert watcher.latest["values"][-1]["Value"] == 42
    await watcher.stop()
    assert server4.last.closed is True


@pytest.mark.asyncio
async def test_watchers_after_unexpected_connection_loss():
    server = FakeServer()
    client = TradingViewClient({"transport": server.transport})
    errors = []
    on_error = lambda error: errors.append(error.code)
    candles = await watchCandles(
        {"symbol": "A", "timeframe": "1", "count": 5, "client": client},
        {"onData": lambda *_: None, "onError": on_error},
    )
    quotes = await watchQuotes(
        {"symbols": ["A"], "fields": "price", "client": client},
        {"onData": lambda *_: None, "onError": on_error},
    )
    assert len(candles.latest) == 5

    server.last.drop(1006, "")
    await asyncio.gather(candles.closed, quotes.closed)
    assert errors == ["DISCONNECTED", "DISCONNECTED"]
    assert [candles.isActive, quotes.isActive, client.isClosed] == [False, False, True]

    server.last.handlers.onMessage('~m~20~m~{"m":"du","p":["x"]}')
    await asyncio.gather(candles.stop(), quotes.stop(), client.close())
    assert len(errors) == 2
    with pytest.raises(Exception) as exc_info:
        await watchCandles({"symbol": "A", "client": client}, {"onData": lambda *_: None})
    assert exc_info.value.code == "INVALID_STATE"

    replacement = TradingViewClient({"transport": server.transport})
    assert (
        len(await getCandles({"symbol": "A", "timeframe": "1", "count": 5, "client": replacement}))
        == 5
    )
    assert replacement.isClosed is False
    await replacement.close()

    server2, client_options2 = fake()
    errors2 = []
    watcher2 = await watchCandles(
        {"symbol": "A", "clientOptions": {**client_options2, "inactivityTimeoutMs": 50}},
        {"onData": lambda *_: None, "onError": lambda error: errors2.append(error.code)},
    )
    await watcher2.closed
    assert errors2 == ["CONNECTION_ERROR"]
    assert server2.last.terminated is True
