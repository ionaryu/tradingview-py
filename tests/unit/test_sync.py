from tradingview import sync
from tests.helpers.fake_server import FakeServer


def test_sync_wrappers_execute_without_running_event_loop():
    server = FakeServer({"history": 20})
    client_opts = {"transport": server.transport}

    candles = sync.get_candles(
        {"symbol": "BINANCE:BTCUSDT", "timeframe": "60", "count": 3, "clientOptions": client_opts}
    )
    assert len(candles) == 3
    assert [c.close for c in candles] == [117, 118, 119]

    quote = sync.getQuote({"symbol": "BINANCE:BTCUSDT", "fields": "price", "clientOptions": client_opts})
    assert quote.lp == 100

    info = sync.get_symbol_info({"symbol": "NASDAQ:AAPL", "clientOptions": client_opts})
    assert info.full_name == "NASDAQ:AAPL"
