import tradingview as root
import tradingview.data as data


def test_root_entry_exposes_high_level_low_level_and_http_apis():
    expected_root = [
        "ALL_QUOTE_FIELDS",
        "BuiltInIndicator",
        "CHART_TYPE_STUDIES",
        "ChartSession",
        "DEFAULT_TIMEOUT_MS",
        "Emitter",
        "PineIndicator",
        "PinePermissionManager",
        "QuoteSession",
        "QuoteSubscription",
        "Study",
        "TradingViewClient",
        "TradingViewError",
        "TradingViewProvider",
        "applyGraphicsCommands",
        "clearIndicatorCache",
        "createProxy",
        "createWsTransport",
        "getCandles",
        "getChartToken",
        "getDrawings",
        "getHotlist",
        "getIndicator",
        "getIndicatorData",
        "getPrivateIndicators",
        "getQuote",
        "getQuotes",
        "getScreener",
        "getSymbolInfo",
        "getTechnicalAnalysis",
        "getUser",
        "getWatchlists",
        "loginUser",
        "mergeStrategyReport",
        "parseGraphics",
        "parseIndicatorDefinition",
        "parseTrades",
        "protocol",
        "quoteSymbolKey",
        "resolveQuoteFields",
        "searchIndicators",
        "searchMarkets",
        "summarizeStrategyReport",
        "timeframeSeconds",
        "toTradingViewError",
        "watchCandles",
        "watchIndicator",
        "watchQuotes",
        "wsTransport",
    ]
    assert sorted(root.JS_EXPORTS) == expected_root
    for name in expected_root:
        assert hasattr(root, name), f"Missing root export: {name}"

    expected_protocol = [
        "createSessionId",
        "decodeCompressed",
        "decodeFrames",
        "encodeFrame",
        "encodeHeartbeat",
        "encodePacket",
        "normaliseBase64",
        "readFirstZipEntry",
    ]
    for name in expected_protocol:
        assert hasattr(root.protocol, name), f"Missing protocol export: {name}"


def test_data_entry_exposes_simplified_data_api():
    expected_data = [
        "DEFAULT_TIMEOUT_MS",
        "TradingViewError",
        "TradingViewProvider",
        "getCandles",
        "getHotlist",
        "getIndicatorData",
        "getQuote",
        "getQuotes",
        "getScreener",
        "getSymbolInfo",
        "getTechnicalAnalysis",
        "getWatchlists",
        "searchIndicators",
        "searchMarkets",
        "summarizeStrategyReport",
        "watchCandles",
        "watchIndicator",
        "watchQuotes",
    ]
    assert sorted(data.JS_EXPORTS) == expected_data
    for name in expected_data:
        assert hasattr(data, name), f"Missing data export: {name}"
    assert data.getCandles is root.getCandles
    assert data.get_candles is root.get_candles
