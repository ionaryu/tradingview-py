import asyncio
import pytest

from tradingview.client.client import TradingViewClient
from tradingview.quote.fields import ALL_QUOTE_FIELDS, resolveQuoteFields
from tradingview.quote.quote_session import quoteSymbolKey
from tests.helpers.fake_server import FakeServer, flush, until


async def setup():
    server = FakeServer()
    client = TradingViewClient({"transport": server.transport})
    await client.ready
    return server, client, server.last


def test_quote_fields_resolves_presets_and_explicit_lists():
    assert resolveQuoteFields("price") == ["lp"]
    assert resolveQuoteFields() == ALL_QUOTE_FIELDS
    assert resolveQuoteFields([]) == ALL_QUOTE_FIELDS
    assert resolveQuoteFields(["lp", "bid"]) == ["lp", "bid"]


@pytest.mark.asyncio
async def test_quote_session_creates_session_with_fields_and_streams_merged_data():
    _, client, connection = await setup()
    session = client.createQuoteSession({"fields": ["lp", "ch"]})
    sub = session.subscribe("BINANCE:BTCEUR")
    events = []
    sub.onAny(lambda event, *args: events.append([event, *args]))
    await until(lambda: sub.isLoaded)

    assert connection.packets("quote_create_session")[0]["p"] == [session.id]
    assert connection.packets("quote_set_fields")[0]["p"] == [session.id, "lp", "ch"]
    assert connection.packets("quote_add_symbols")[0]["p"] == [
        session.id,
        quoteSymbolKey("BINANCE:BTCEUR"),
    ]

    connection.push({"m": "qsd", "p": [session.id, {"n": sub.key, "s": "ok", "v": {"lp": 101}}]})
    assert sub.data["lp"] == 101
    assert sub.data["ch"] == 1
    assert sub.data["description"] == "Fake BINANCE:BTCEUR"
    assert [e[0] for e in events] == ["data", "loaded", "data"]
    assert events[2][2] == {"lp": 101}

    session.setFields("price")
    assert connection.packets("quote_set_fields")[1]["p"] == [session.id, "lp"]
    await client.close()


@pytest.mark.asyncio
async def test_quote_session_shares_one_server_subscription_with_ref_counting():
    _, client, connection = await setup()
    session = client.createQuoteSession()
    a = session.subscribe("BINANCE:BTCEUR")
    await until(lambda: a.isLoaded)
    b = session.subscribe("BINANCE:BTCEUR")
    extended = session.subscribe("BINANCE:BTCEUR", {"session": "extended"})
    await until(lambda: b.isLoaded and extended.isLoaded)
    assert b.data["lp"] == 100
    assert len(connection.packets("quote_add_symbols")) == 2

    a.close()
    assert len(connection.packets("quote_remove_symbols")) == 0
    b.close()
    b.close()
    assert [p["p"] for p in connection.packets("quote_remove_symbols")] == [
        [session.id, quoteSymbolKey("BINANCE:BTCEUR")]
    ]
    session.delete()
    session.delete()
    assert len(connection.packets("quote_delete_session")) == 1
    assert extended.isClosed is True
    with pytest.raises(Exception, match="deleted"):
        session.subscribe("X")
    await client.close()


@pytest.mark.asyncio
async def test_quote_session_reports_symbol_errors_and_removes_orphan_symbols():
    _, client, connection = await setup()
    session = client.createQuoteSession()
    bad = session.subscribe("XXXXX")
    fut = asyncio.get_running_loop().create_future()
    bad.on("error", lambda err: fut.set_result(err) if not fut.done() else None)
    error = await fut
    assert error.code == "QUOTE_ERROR"
    assert error.message == "Quote error (XXXXX): no_such_symbol"

    connection.push({"m": "qsd", "p": [session.id, {"n": "orphan", "s": "ok", "v": {}}]})
    await flush()
    assert connection.packets("quote_remove_symbols")[-1]["p"] == [session.id, "orphan"]
    await client.close()


@pytest.mark.asyncio
async def test_quote_session_reports_disconnected_on_unexpected_disconnection():
    _, client, connection = await setup()
    session = client.createQuoteSession()
    sub = session.subscribe("BINANCE:BTCEUR")
    errors = []
    sub.on("error", lambda e: errors.append(e.code))
    session.on("error", lambda e: errors.append(f"session:{e.code}"))
    connection.drop()
    assert errors == ["session:DISCONNECTED", "DISCONNECTED"]
    assert client.isClosed is True
