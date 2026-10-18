# `@mathieuc/tradingview` (v4.0.0) Python Port Design Specification

**Date:** 2026-10-18  
**Source Package:** `@mathieuc/tradingview` v4.0.0 (`Mathieu2301/TradingView-API`)  
**Target Environment:** Python 3.11+ managed via `uv`

---

## 1. Overview & Goals

Port the `@mathieuc/tradingview` (v4.0.0) TypeScript library to Python with 1:1 functional parity, covering:
1. **Protocol Layer**: WebSocket framing (`~m~<len>~m~<payload>` using UTF-16 code unit lengths), heartbeats (`~h~<id>`), session ID generation, and strategy report decompression (ZIP / raw deflate / zlib / gzip / base64).
2. **Low-Level Client & Sessions**:
   - `TradingViewClient`: WebSocket lifecycle, authentication token fetches/updates, packet routing, automatic reconnect, HTTP/SOCKS proxy support, custom transports.
   - `ChartSession`: Market resolution, series creation/modification/pagination (`fetchMore`), replay mode (`startReplay`, `stepReplay`, `startAutoReplay`, `stopAutoReplay`, `endReplay`).
   - `StudySession`: Built-in and Pine indicators, plot value extraction, strategy report parsing, and Pine graphics/drawing parsing (`lines`, `boxes`, `labels`, `tables`, `polygons`, `polylines`, `horizlines`, `hhists`, `tpo`).
   - `QuoteSession`: Real-time quote subscriptions across 60+ standard quote fields.
3. **HTTP API**:
   - Market symbol search (`search_markets` / `searchMarkets`)
   - Technical analysis ratings (`get_technical_analysis` / `getTechnicalAnalysis`)
   - Indicator search, metadata fetch, and translation (`search_indicators`, `get_indicator`, `get_private_indicators`, `compile_pine`)
   - Account login & info (`login_user`, `get_user`)
   - Screeners & hotlists (`get_screener`, `get_hotlist`)
   - Watchlists (`get_watchlists`, `get_watchlist_symbols`)
   - Chart layouts (`get_chart_layouts`, `get_chart_drawings`)
   - Pine permissions (`get_pine_permission_users`, `add_pine_permission_user`, `modify_pine_permission_user`, `remove_pine_permission_user`)
4. **High-Level Data API**:
   - `get_candles`, `watch_candles`
   - `get_quote`, `get_quotes`, `watch_quotes`
   - `get_indicator_data`, `watch_indicator`
   - `get_symbol_info`
   - Shared `run_operation` / `create_watcher` abstractions with timeouts, cancellation (`AbortSignal` / `asyncio.Event`), and automatic resource cleanup.
5. **Synchronous Wrapper (`tradingview.sync`) & CLI (`tradingview`)**:
   - Synchronous helper functions (`get_candles_sync`, `get_quote_sync`, `get_quotes_sync`, `get_indicator_data_sync`, `get_symbol_info_sync`, `search_markets_sync`, `get_technical_analysis_sync`, etc.) for non-async scripts and notebooks.
   - CLI entry point (`tradingview`) porting `quick-start.ts`.

---

## 2. Package Architecture & File Mapping

```text
e:\tradingview\
├── pyproject.toml
├── README.md
├── docs/
│   └── superpowers/
│       ├── specs/
│       │   └── 2026-10-18-tradingview-python-port-design.md
│       └── plans/
├── src/
│   └── tradingview/
│       ├── __init__.py              # Top-level exports (snake_case + camelCase aliases)
│       ├── errors.py                # TradingViewError, TradingViewErrorCode, to_trading_view_error
│       ├── events.py                # Emitter (on, once, off, on_any, listener_count)
│       ├── quick_start.py           # CLI launcher & interactive quick-start
│       ├── sync.py                  # Synchronous wrappers for Data & HTTP APIs
│       ├── protocol/
│       │   ├── __init__.py
│       │   ├── framing.py           # decode_frames, encode_frame, encode_packet, encode_heartbeat
│       │   ├── compression.py       # normalise_base64, read_first_zip_entry, decode_compressed
│       │   └── ids.py               # gen_session_id
│       ├── client/
│       │   ├── __init__.py
│       │   ├── transport.py         # Transport protocol & WebSocketsTransport
│       │   ├── proxy.py             # Proxy configuration, URL parsing, HTTP CONNECT / SOCKS5
│       │   └── client.py            # TradingViewClient
│       ├── chart/
│       │   ├── __init__.py
│       │   ├── types.py             # Candle, SymbolInfo, Timeframe, ChartOptions, etc.
│       │   ├── timeframes.py        # Timeframe constants and validation
│       │   ├── graphics.py          # parse_graphics and graphic types
│       │   ├── strategy.py          # parse_strategy_report and StrategyReport types
│       │   ├── study.py             # StudySession
│       │   └── chart_session.py     # ChartSession
│       ├── quote/
│       │   ├── __init__.py
│       │   ├── fields.py            # QUOTE_FIELDS, DEFAULT_QUOTE_FIELDS, QuoteData
│       │   └── quote_session.py     # QuoteSession
│       ├── indicators/
│       │   ├── __init__.py
│       │   ├── builtin_indicator.py # BuiltInIndicator
│       │   └── pine_indicator.py    # PineIndicator, InputSpec, PlotSpec
│       ├── http/
│       │   ├── __init__.py
│       │   ├── request.py           # Async HTTP client wrapper (httpx) with cookie/header handling
│       │   ├── market.py            # search_markets, get_technical_analysis
│       │   ├── indicators.py        # search_indicators, get_indicator, get_private_indicators
│       │   ├── account.py           # login_user, get_user, get_auth_token
│       │   ├── screener.py          # get_screener, get_hotlist
│       │   ├── watchlists.py        # get_watchlists
│       │   ├── layouts.py           # get_layouts, get_drawings
│       │   └── pine_permissions.py  # Pine script access management
│       └── data/
│           ├── __init__.py
│           ├── operation.py         # run_operation, create_watcher, AbortSignal support
│           ├── provider.py          # Client provider/pooling helper
│           ├── candles.py           # get_candles, watch_candles
│           ├── history.py           # Deep history pagination (from/to/max_bars)
│           ├── quotes.py            # get_quote, get_quotes, watch_quotes
│           ├── indicators.py        # get_indicator_data, watch_indicator
│           └── symbols.py           # get_symbol_info
└── tests/
    ├── fixtures/
    │   ├── compressed-report.json
    │   └── live-session.json
    ├── helpers/
    │   ├── fake_server.py
    │   └── indicators.py
    └── unit/
        ├── test_protocol.py
        ├── test_events.py
        ├── test_transport.py
        ├── test_proxy.py
        ├── test_client.py
        ├── test_chart.py
        ├── test_study.py
        ├── test_strategy.py
        ├── test_quote.py
        ├── test_indicators.py
        ├── test_http.py
        ├── test_screener.py
        ├── test_watchlists.py
        ├── test_operation.py
        ├── test_data.py
        ├── test_quick_start.py
        └── test_exports.py
```

---

## 3. Data Types & API Conventions

- **Dual Naming Convention**:
  - Pythonic `snake_case` names are primary (`get_candles`, `watch_candles`, `create_chart`, `set_market`, `fetch_more`).
  - Original TypeScript `camelCase` aliases (`getCandles`, `watchCandles`, `createChart`, `setMarket`, `fetchMore`) are provided on classes and modules so code ported directly from JS/TS works seamlessly.
- **Data Access**:
  - Data dictionaries/objects (`Candle`, `SymbolInfo`, `QuoteData`, `StrategyReport`, etc.) use custom dict/dataclass hybrids (`AttrDict` or dataclasses with `[]` and `.attr` access) so both `candle.close` and `candle["close"]` work effortlessly in Python.
- **UTF-16 Framing**:
  - JavaScript `string.length` measures UTF-16 code units. In Python, `utf16_len(s) = len(s.encode("utf-16-le")) // 2`, and slicing in `decode_frames` operates on UTF-16 code units when non-ASCII characters are present, ensuring 100% compatibility with multi-byte Unicode strings in TradingView frames.

---

## 4. Error Handling & Cancellation

- `TradingViewError` inherits from `Exception` with `.code` (`TradingViewErrorCode`), `.message`, `.details`, and `__cause__`.
- Cancellation supports `asyncio.Event` or a lightweight `AbortSignal` / `AbortController` helper class (mirroring JS `AbortController` for 1:1 ergonomics plus standard Python `asyncio.CancelledError` handling).

---

## 5. Testing Strategy

- All 17 unit test suites from `@mathieuc/tradingview` (`tests/unit/*.test.ts`) will be ported to `pytest` + `pytest-asyncio`.
- A local `FakeServer` (ported from `tests/helpers/fake-server.ts`) using `websockets.serve` and mock HTTP servers (`aiohttp`/`http.server` or `httpx.MockTransport`) will test WebSocket framing, reconnection, chart sessions, studies, strategies, quotes, HTTP endpoints, proxies, and high-level Data API functions offline.
