import json
import pytest

from tradingview._types import AbortController, FetchHeaders, FetchResponse
from tradingview.http.watchlists import getHotlist, getWatchlists

CREDENTIALS = {"session": "fixture", "signature": "signed"}


def reply(data, status=200):
    async def fetch(*_):
        return FetchResponse(status=status, headers=FetchHeaders(), body=json.dumps(data))

    return fetch


@pytest.mark.asyncio
async def test_get_watchlists_reads_ordered_entries_and_metadata():
    lists = [
        {
            "id": 1,
            "name": "Example",
            "symbols": ["###Section", "NASDAQ:AAPL", "BINANCE:BTCUSDT"],
            "active": True,
        }
    ]
    controller = AbortController()

    async def fetch(url, init=None):
        assert url == "https://www.tradingview.com/api/v1/symbols_list/all/"
        assert init.get("redirect") == "manual"
        assert init.get("method") == "GET"
        assert init.get("signal") is controller.signal
        assert init["headers"]["cookie"] == "sessionid=fixture;sessionid_sign=signed"
        return FetchResponse(status=200, headers=FetchHeaders(), body=json.dumps(lists))

    assert (
        await getWatchlists(
            {"credentials": CREDENTIALS, "fetch": fetch, "signal": controller.signal}
        )
        == lists
    )


@pytest.mark.asyncio
async def test_get_watchlists_supports_empty_lists_and_rejects_missing_credentials():
    assert await getWatchlists({"credentials": CREDENTIALS, "fetch": reply([])}) == []
    with pytest.raises(Exception) as exc_info:
        await getWatchlists({"credentials": {"session": ""}})
    assert exc_info.value.code == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_get_watchlists_distinguishes_access_rejection_from_malformed_data():
    for status in [301, 302, 401, 403]:
        with pytest.raises(Exception) as exc_auth:
            await getWatchlists({"credentials": CREDENTIALS, "fetch": reply({}, status)})
        assert exc_auth.value.code == "AUTH_ERROR"

    for data in [{}, [None], [{"id": 1, "name": "x", "symbols": [42]}]]:
        with pytest.raises(Exception) as exc_http:
            await getWatchlists({"credentials": CREDENTIALS, "fetch": reply(data)})
        assert exc_http.value.code == "HTTP_ERROR"

    with pytest.raises(Exception) as exc_429:
        await getWatchlists({"credentials": CREDENTIALS, "fetch": reply([], 429)})
    assert exc_429.value.code == "HTTP_ERROR"


@pytest.mark.asyncio
async def test_get_hotlist_ranks_requested_universe_and_preserves_filters():
    for kind, sort_by, sort_order in [
        ("gainers", "change", "desc"),
        ("losers", "change", "asc"),
        ("mostActive", "volume", "desc"),
        ("volumeGainers", "relative_volume_10d_calc", "desc"),
    ]:

        async def fetch(url, init=None, sb=sort_by, so=sort_order):
            assert url == "https://scanner.tradingview.com/crypto/scan"
            body = json.loads(init["body"])
            assert body["columns"] == ["close"]
            assert body["sort"] == {"sortBy": sb, "sortOrder": so}
            assert body["filter"] == []
            assert body["range"] == [5, 10]
            return FetchResponse(
                status=200,
                headers=FetchHeaders(),
                body=json.dumps({"totalCount": 0, "data": []}),
            )

        await getHotlist(
            {"kind": kind, "market": "crypto", "columns": ["close"], "filter": [], "range": [5, 10]},
            {"fetch": fetch},
        )


@pytest.mark.asyncio
async def test_get_hotlist_defaults_to_america_stocks_and_rejects_unknown_kinds():
    async def fetch(url, init=None):
        assert url == "https://scanner.tradingview.com/america/scan"
        body = json.loads(init["body"])
        assert body["filter"] == [{"left": "type", "operation": "equal", "right": "stock"}]
        return FetchResponse(
            status=200,
            headers=FetchHeaders(),
            body=json.dumps({"totalCount": 0, "data": []}),
        )

    await getHotlist({"kind": "gainers"}, {"fetch": fetch})
    with pytest.raises(Exception) as exc_info:
        await getHotlist({"kind": "unknown"}, {"fetch": fetch})
    assert exc_info.value.code == "INVALID_ARGUMENT"
