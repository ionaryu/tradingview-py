import json
import pytest

from tradingview._types import AbortController, FetchHeaders, FetchResponse
from tradingview.http.screener import getScreener


def reply(data, status=200):
    async def fetch(*_):
        return FetchResponse(status=status, headers=FetchHeaders(), body=json.dumps(data))

    return fetch


@pytest.mark.asyncio
async def test_get_screener_forwards_filters_sort_auth_and_cancellation():
    controller = AbortController()

    async def fetch(url, init=None):
        assert url == "https://scanner.tradingview.com/america/scan"
        assert init.get("signal") is controller.signal
        assert init["headers"]["cookie"] == "sessionid=test;sessionid_sign=signed"
        assert json.loads(init["body"]) == {
            "columns": ["close", "Stoch.RSI.D", "name"],
            "range": [10, 20],
            "filter": [{"left": "close", "operation": "greater", "right": 10}],
            "sort": {"sortBy": "close", "sortOrder": "desc"},
            "symbols": {"tickers": ["NASDAQ:AAPL"]},
        }
        return FetchResponse(
            status=200,
            headers=FetchHeaders(),
            body=json.dumps(
                {"totalCount": 100, "data": [{"s": "NASDAQ:AAPL", "d": [12, None, "Apple"]}]}
            ),
        )

    res = await getScreener(
        {
            "market": "america",
            "columns": ["close", "Stoch.RSI.D", "name"],
            "range": [10, 20],
            "filter": [{"left": "close", "operation": "greater", "right": 10}],
            "sort": {"sortBy": "close", "sortOrder": "desc"},
            "symbols": ["NASDAQ:AAPL"],
        },
        {
            "fetch": fetch,
            "signal": controller.signal,
            "credentials": {"session": "test", "signature": "signed"},
        },
    )
    assert res == {
        "totalCount": 100,
        "rows": [
            {
                "symbol": "NASDAQ:AAPL",
                "values": {"close": 12, "Stoch.RSI.D": None, "name": "Apple"},
            }
        ],
    }


@pytest.mark.asyncio
async def test_get_screener_accepts_empty_page_and_preserves_special_column_names():
    assert await getScreener(
        {"columns": ["close"]}, {"fetch": reply({"totalCount": 0, "data": []})}
    ) == {"totalCount": 0, "rows": []}
    result = await getScreener(
        {"columns": ["__proto__"]},
        {"fetch": reply({"totalCount": 1, "data": [{"s": "X:Y", "d": [42]}]})},
    )
    assert "__proto__" in result["rows"][0]["values"]
    assert result["rows"][0]["values"]["__proto__"] == 42


@pytest.mark.asyncio
async def test_get_screener_rejects_unsafe_paths_ambiguous_columns_and_invalid_ranges():
    async def must_not_fetch(*_):
        raise RuntimeError("must not fetch")

    for query in [
        {"market": "../x", "columns": ["close"]},
        {"columns": []},
        {"columns": ["close", "close"]},
        {"columns": [""]},
        {"columns": ["close"], "range": [-1, 2]},
        {"columns": ["close"], "range": [0, 0]},
        {"columns": ["close"], "range": [0, 1.5]},
    ]:
        with pytest.raises(Exception) as exc_info:
            await getScreener(query, {"fetch": must_not_fetch})
        assert exc_info.value.code == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_get_screener_rejects_non_success_statuses_and_malformed_rows():
    for data in [
        {"error": "Unknown field"},
        {"totalCount": -1, "data": []},
        {"totalCount": 1, "data": [{"s": "X:Y", "d": []}]},
        {"totalCount": 1, "data": [None]},
    ]:
        with pytest.raises(Exception) as exc_info:
            await getScreener({"columns": ["close"]}, {"fetch": reply(data)})
        assert exc_info.value.code == "HTTP_ERROR"

    with pytest.raises(Exception) as exc_429:
        await getScreener({"columns": ["close"]}, {"fetch": reply({"totalCount": 0, "data": []}, 429)})
    assert exc_429.value.code == "HTTP_ERROR"
