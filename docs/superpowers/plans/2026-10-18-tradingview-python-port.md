# `@mathieuc/tradingview` (v4.0.0) Python Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port `@mathieuc/tradingview` v4.0.0 to Python 3.11+ with 1:1 feature parity, unit tests, synchronous wrappers, CLI, and publish to GitHub with GitHub Desktop integration.

**Architecture:** Modular `asyncio`-first Python package (`src/tradingview/`) mirroring `@mathieuc/tradingview` v4 (`errors`, `events`, `protocol`, `client`, `chart`, `quote`, `indicators`, `http`, `data`, `sync`, `quick_start`), backed by `websockets` and `httpx`, managed via `uv`, and verified with `pytest` + `pytest-asyncio` offline test suites.

**Tech Stack:** Python 3.11+, `uv`, `websockets>=13.0`, `httpx>=0.27`, `pytest>=8.0`, `pytest-asyncio>=0.24`

## Global Constraints

- Target Environment: Python 3.11+ managed via `uv` in `e:\tradingview`
- Dual Naming Convention: Primary `snake_case` names AND original TypeScript `camelCase` aliases exported on classes and modules
- Data Access: Dict/attribute hybrid objects (`AttrDict`) so both `obj.field` and `obj["field"]` work seamlessly
- Framing: UTF-16 code unit length (`len(body.encode("utf-16-le")) // 2`) in `~m~<len>~m~<payload>`
- Every library error must be an instance of `TradingViewError` with one of the 18 `TradingViewErrorCode` strings

---

### Task 1: Project Scaffolding, Core Types (`AttrDict`), `errors.py`, `events.py`, and `protocol/`

**Files:**
- Create: `pyproject.toml`
- Create: `src/tradingview/_types.py`
- Create: `src/tradingview/errors.py`
- Create: `src/tradingview/events.py`
- Create: `src/tradingview/protocol/ids.py`
- Create: `src/tradingview/protocol/framing.py`
- Create: `src/tradingview/protocol/compression.py`
- Create: `src/tradingview/protocol/__init__.py`
- Test: `tests/unit/test_events.py`
- Test: `tests/unit/test_protocol.py`

**Interfaces:**
- Produces:
  - `AttrDict`: `dict` subclass supporting `.attr` access and recursive wrapping
  - `TradingViewError(code, message, *, details=None, cause=None)`
  - `to_trading_view_error` / `toTradingViewError`
  - `Emitter`: `on`, `once`, `off`, `on_any`/`onAny`, `listener_count`/`listenerCount`, `_emit`, `_has_listeners`, `_remove_all_listeners`
  - `protocol`: `decode_frames`/`decodeFrames`, `encode_frame`/`encodeFrame`, `encode_packet`/`encodePacket`, `encode_heartbeat`/`encodeHeartbeat`, `normalise_base64`/`normaliseBase64`, `read_first_zip_entry`/`readFirstZipEntry`, `decode_compressed`/`decodeCompressed`, `gen_session_id`/`genSessionId`

- [ ] **Step 1: Initialize `uv` environment, `pyproject.toml`, and copy test fixtures**
- [ ] **Step 2: Write `tests/unit/test_events.py` and `tests/unit/test_protocol.py`**
- [ ] **Step 3: Implement `errors.py`, `events.py`, `_types.py`, and `protocol/*`**
- [ ] **Step 4: Run `uv run pytest tests/unit/test_events.py tests/unit/test_protocol.py -v` and verify PASS**
- [ ] **Step 5: Commit Task 1**

---

### Task 2: Transport, Proxy, and `TradingViewClient` (`src/tradingview/client/`)

**Files:**
- Create: `src/tradingview/client/proxy.py`
- Create: `src/tradingview/client/transport.py`
- Create: `src/tradingview/client/client.py`
- Create: `src/tradingview/client/__init__.py`
- Create: `tests/helpers/fake_server.py`
- Test: `tests/unit/test_proxy.py`
- Test: `tests/unit/test_transport.py`
- Test: `tests/unit/test_client.py`

**Interfaces:**
- Consumes: `errors`, `events.Emitter`, `protocol`
- Produces:
  - `parse_proxy_url`/`parseProxyUrl`, `redact_proxy_url`/`redactProxyUrl`, `open_proxy_tunnel`/`openProxyTunnel`, `create_proxy_transport`/`createProxyTransport`
  - `create_web_socket_transport`/`createWebSocketTransport`
  - `TradingViewClient` (`connect`, `close`, `send`, `send_raw`/`sendRaw`, `set_credentials`/`setCredentials`, `register_session`/`registerSession`, `create_chart`/`createChart`, `create_quote_session`/`createQuoteSession`, `wait_ready`/`waitReady`)

- [ ] **Step 1: Write `tests/helpers/fake_server.py`, `tests/unit/test_proxy.py`, `tests/unit/test_transport.py`, and `tests/unit/test_client.py`**
- [ ] **Step 2: Implement `client/proxy.py`, `client/transport.py`, `client/client.py`, and `client/__init__.py`**
- [ ] **Step 3: Run `uv run pytest tests/unit/test_proxy.py tests/unit/test_transport.py tests/unit/test_client.py -v` and verify PASS**
- [ ] **Step 4: Commit Task 2**

---

### Task 3: Indicators, Quote Session, Chart Session, Study, Graphics, and Strategy (`indicators/`, `quote/`, `chart/`)

**Files:**
- Create: `src/tradingview/indicators/builtin_indicator.py`
- Create: `src/tradingview/indicators/pine_indicator.py`
- Create: `src/tradingview/indicators/__init__.py`
- Create: `src/tradingview/quote/fields.py`
- Create: `src/tradingview/quote/quote_session.py`
- Create: `src/tradingview/quote/__init__.py`
- Create: `src/tradingview/chart/timeframes.py`
- Create: `src/tradingview/chart/types.py`
- Create: `src/tradingview/chart/graphics.py`
- Create: `src/tradingview/chart/strategy.py`
- Create: `src/tradingview/chart/study.py`
- Create: `src/tradingview/chart/chart_session.py`
- Create: `src/tradingview/chart/__init__.py`
- Create: `tests/helpers/indicators.py`
- Test: `tests/unit/test_indicators.py`
- Test: `tests/unit/test_quote.py`
- Test: `tests/unit/test_chart.py`
- Test: `tests/unit/test_study.py`
- Test: `tests/unit/test_strategy.py`

**Interfaces:**
- Consumes: `errors`, `events.Emitter`, `protocol`, `client`
- Produces:
  - `BuiltInIndicator`, `PineIndicator`
  - `QUOTE_FIELDS`, `DEFAULT_QUOTE_FIELDS`, `QuoteSession`
  - `TIMEFRAMES`, `is_timeframe`/`isTimeframe`, `assert_timeframe`/`assertTimeframe`
  - `parse_graphics`/`parseGraphics`, `parse_strategy_report`/`parseStrategyReport`
  - `StudySession`, `ChartSession`

- [ ] **Step 1: Write unit tests (`test_indicators.py`, `test_quote.py`, `test_chart.py`, `test_study.py`, `test_strategy.py`)**
- [ ] **Step 2: Implement `indicators/*`, `quote/*`, and `chart/*`**
- [ ] **Step 3: Run `uv run pytest tests/unit/test_indicators.py tests/unit/test_quote.py tests/unit/test_chart.py tests/unit/test_study.py tests/unit/test_strategy.py -v` and verify PASS**
- [ ] **Step 4: Commit Task 3**

---

### Task 4: HTTP API (`src/tradingview/http/`)

**Files:**
- Create: `src/tradingview/http/request.py`
- Create: `src/tradingview/http/market.py`
- Create: `src/tradingview/http/indicators.py`
- Create: `src/tradingview/http/account.py`
- Create: `src/tradingview/http/screener.py`
- Create: `src/tradingview/http/watchlists.py`
- Create: `src/tradingview/http/layouts.py`
- Create: `src/tradingview/http/pine_permissions.py`
- Create: `src/tradingview/http/__init__.py`
- Test: `tests/unit/test_http.py`
- Test: `tests/unit/test_screener.py`
- Test: `tests/unit/test_watchlists.py`

**Interfaces:**
- Consumes: `errors`, `indicators`
- Produces:
  - `request_json`/`requestJson`, `session_cookie`/`sessionCookie`
  - `search_markets`/`searchMarkets`, `get_technical_analysis`/`getTechnicalAnalysis`
  - `search_indicators`/`searchIndicators`, `get_indicator`/`getIndicator`, `get_private_indicators`/`getPrivateIndicators`, `parse_raw_indicator`/`parseRawIndicator`
  - `login_user`/`loginUser`, `get_user`/`getUser`
  - `get_screener`/`getScreener`, `get_hotlist`/`getHotlist`, `SCREENER_MARKETS`
  - `get_watchlists`/`getWatchlists`, `get_active_watchlist`/`getActiveWatchlist`
  - `get_drawings`/`getDrawings`, `get_layout_token`/`getLayoutToken`
  - `get_pine_perm_users`/`getPinePermUsers`, `add_pine_perm_user`/`addPinePermUser`, `modify_pine_perm_expiration`/`modifyPinePermExpiration`, `remove_pine_perm_user`/`removePinePermUser`

- [ ] **Step 1: Write unit tests (`test_http.py`, `test_screener.py`, `test_watchlists.py`)**
- [ ] **Step 2: Implement `src/tradingview/http/*`**
- [ ] **Step 3: Run `uv run pytest tests/unit/test_http.py tests/unit/test_screener.py tests/unit/test_watchlists.py -v` and verify PASS**
- [ ] **Step 4: Commit Task 4**

---

### Task 5: High-Level Data API, Sync Wrappers, CLI, and Top-Level Exports (`data/`, `sync.py`, `quick_start.py`, `__init__.py`)

**Files:**
- Create: `src/tradingview/data/operation.py`
- Create: `src/tradingview/data/provider.py`
- Create: `src/tradingview/data/candles.py`
- Create: `src/tradingview/data/history.py`
- Create: `src/tradingview/data/quotes.py`
- Create: `src/tradingview/data/indicators.py`
- Create: `src/tradingview/data/symbols.py`
- Create: `src/tradingview/data/__init__.py`
- Create: `src/tradingview/sync.py`
- Create: `src/tradingview/quick_start.py`
- Create: `src/tradingview/__init__.py`
- Create: `README.md`
- Test: `tests/unit/test_operation.py`
- Test: `tests/unit/test_data.py`
- Test: `tests/unit/test_quick_start.py`
- Test: `tests/unit/test_exports.py`

**Interfaces:**
- Consumes: `errors`, `events`, `protocol`, `client`, `chart`, `quote`, `indicators`, `http`
- Produces:
  - `get_candles`/`getCandles`, `watch_candles`/`watchCandles`, `get_candles_history`/`getCandlesHistory`
  - `get_quote`/`getQuote`, `get_quotes`/`getQuotes`, `watch_quotes`/`watchQuotes`
  - `get_indicator_data`/`getIndicatorData`, `watch_indicator`/`watchIndicator`
  - `get_symbol_info`/`getSymbolInfo`
  - `sync`: synchronous wrappers (`get_candles_sync`, `get_quote_sync`, etc.)
  - `quick_start`: CLI runner (`run_quick_start`/`runQuickStart`, `parse_quick_start_args`/`parseQuickStartArgs`)

- [ ] **Step 1: Write unit tests (`test_operation.py`, `test_data.py`, `test_quick_start.py`, `test_exports.py`)**
- [ ] **Step 2: Implement `data/*`, `sync.py`, `quick_start.py`, `__init__.py`, and `README.md`**
- [ ] **Step 3: Run full test suite (`uv run pytest -v`) and CLI smoke test**
- [ ] **Step 4: Commit Task 5 and publish to GitHub / open in GitHub Desktop**
