# TradingView-API (Python Port)

Python 1:1 port of [`@mathieuc/tradingview`](https://github.com/Mathieu2301/TradingView-API) (v4.0.0) — fetch historical candles, real-time quotes, Pine Script indicators, strategies, screener queries, watchlists, and technical analysis from TradingView via WebSockets and HTTP.

## Features

- **High-Level Data API (`tradingview.data` / `tradingview`)**:
  - `get_candles` / `getCandles`, `watch_candles` / `watchCandles` (including deep history pagination and custom chart types: HeikinAshi, Renko, LineBreak, Kagi, PointAndFigure, Range)
  - `get_quote` / `getQuote`, `get_quotes` / `getQuotes`, `watch_quotes` / `watchQuotes`
  - `get_indicator_data` / `getIndicatorData`, `watch_indicator` / `watchIndicator` (built-in studies, Pine Script indicators, drawings/graphics, and strategy backtest reports)
  - `get_symbol_info` / `getSymbolInfo`
- **Synchronous Convenience API (`tradingview.sync`)**:
  - Blocking wrappers (`sync.get_candles`, `sync.get_quote`, `sync.get_indicator_data`, `sync.search_markets`, `sync.get_screener`, etc.) for scripts and notebooks without managing `asyncio` loops manually.
- **HTTP & Account API (`tradingview.http`)**:
  - `search_markets` / `searchMarkets`, `search_indicators` / `searchIndicators`, `get_indicator` / `getIndicator`, `get_private_indicators` / `getPrivateIndicators`
  - `get_technical_analysis` / `getTechnicalAnalysis`, `get_screener` / `getScreener`, `get_watchlists` / `getWatchlists`, `get_hotlist` / `getHotlist`
  - `login_user` / `loginUser`, `get_user` / `getUser`, `get_chart_token` / `getChartToken`, `get_drawings` / `getDrawings`, `PinePermissionManager`
- **Low-Level Session API (`tradingview.client`, `tradingview.chart`, `tradingview.quote`)**:
  - `TradingViewClient`, `ChartSession` (including historical bar replay mode), `Study`, `QuoteSession`, `QuoteSubscription`, and HTTP `CONNECT` proxy support (`create_proxy` / `createProxy`).
- **Dual Naming & Attribute Access**:
  - Supports both Pythonic `snake_case` and original TypeScript `camelCase` method/function names, and returned dictionaries (`AttrDict`) support both `row["close"]` and `row.close`.

---

## Installation (with `uv`)

```bash
uv sync
```

Run tests:

```bash
uv run pytest -v
```

---

## Quick Start

### 1. Asynchronous API (`asyncio`)

```python
import asyncio
from tradingview import get_candles, get_quote, get_indicator_data, search_markets

async def main():
    # Fetch the 100 most recent 1-hour candles
    candles = await get_candles({"symbol": "BINANCE:BTCUSDT", "timeframe": "60", "count": 100})
    print("Latest candle:", candles[-1])

    # Fetch real-time quote
    quote = await get_quote("BINANCE:BTCUSDT")
    print("Last price:", quote.lp)

    # Compute an indicator (e.g. RSI)
    rsi = await get_indicator_data({
        "symbol": "BINANCE:BTCUSDT",
        "timeframe": "D",
        "indicator": "STD;RSI",
        "count": 50,
    })
    print("Latest RSI values:", rsi.values[-1])

    # Search markets
    markets = await search_markets("BTCUSDT", {"type": "crypto"})
    print("Top match:", markets[0].id)

asyncio.run(main())
```

### 2. Synchronous API (`tradingview.sync`)

```python
from tradingview import sync

candles = sync.get_candles({"symbol": "BINANCE:BTCUSDT", "timeframe": "60", "count": 10})
print(candles[-1].close)

quote = sync.get_quote("NASDAQ:AAPL")
print(quote.lp)
```

### 3. Streaming Real-Time Updates

```python
import asyncio
from tradingview import watch_candles

async def main():
    watcher = await watch_candles(
        {"symbol": "BINANCE:BTCUSDT", "timeframe": "1", "count": 5},
        {"on_data": lambda candles: print("Latest close:", candles[-1].close)},
    )
    await asyncio.sleep(10)
    await watcher.stop()

asyncio.run(main())
```

---

## Disclaimer

This is an independent community port of [`@mathieuc/tradingview`](https://github.com/Mathieu2301/TradingView-API) and is not affiliated with or endorsed by TradingView.
