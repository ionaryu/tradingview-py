from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlparse
import pytest

from tradingview._types import AbortError, FetchHeaders, FetchResponse
from tradingview.http import (
    PinePermissionManager,
    getChartToken,
    getDrawings,
    getIndicator,
    getPrivateIndicators,
    getTechnicalAnalysis,
    getUser,
    loginUser,
    searchIndicators,
    searchMarkets,
)


def mock_fetch(route):
    calls = []

    async def fetch(url: str, init=None):
        init = init or {}
        parsed = urlparse(url)
        calls.append({"url": url, "parsed": parsed, "init": init})
        res = route(parsed, init, url)
        if hasattr(res, "__await__"):
            return await res
        return res

    return fetch, calls


def json_resp(body, status=200, headers=None):
    hdrs = dict(headers) if isinstance(headers, dict) else list(headers or [])
    if isinstance(hdrs, list):
        hdrs.append(("content-type", "application/json"))
    else:
        hdrs["content-type"] = "application/json"
    return FetchResponse(status=status, headers=FetchHeaders(hdrs), body=json.dumps(body))


def query_dict(parsed):
    return {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}


@pytest.mark.asyncio
async def test_search_markets_queries_symbol_search_v3():
    fetch, calls = mock_fetch(
        lambda *_: json_resp(
            {
                "symbols": [
                    {
                        "symbol": "<em>BTC</em>USD",
                        "exchange": "Binance",
                        "description": "Bitcoin / <em>US</em> Dollar",
                        "type": "spot",
                        "currency_code": "USD",
                    },
                    {
                        "symbol": "AAPL",
                        "exchange": "NASDAQ Stock Market",
                        "prefix": "NASDAQ",
                        "description": "Apple",
                        "type": "stock",
                        "country": "US",
                    },
                ]
            }
        )
    )
    results = await searchMarkets("binance:btc usd", {"type": "crypto", "offset": 50, "fetch": fetch})
    p = calls[0]["parsed"]
    assert f"{p.scheme}://{p.netloc}{p.path}" == "https://symbol-search.tradingview.com/symbol_search/v3/"
    assert query_dict(p) == {
        "text": "BTC USD",
        "exchange": "BINANCE",
        "search_type": "crypto",
        "start": "50",
    }
    assert calls[0]["init"]["headers"]["origin"] == "https://www.tradingview.com"
    assert results == [
        {
            "id": "BINANCE:BTCUSD",
            "exchange": "Binance",
            "fullExchange": "Binance",
            "symbol": "BTCUSD",
            "description": "Bitcoin / US Dollar",
            "type": "spot",
            "currency": "USD",
            "country": None,
        },
        {
            "id": "NASDAQ:AAPL",
            "exchange": "NASDAQ",
            "fullExchange": "NASDAQ Stock Market",
            "symbol": "AAPL",
            "description": "Apple",
            "type": "stock",
            "currency": None,
            "country": "US",
        },
    ]


@pytest.mark.asyncio
async def test_search_markets_combines_country_and_sector_filters():
    fetch, calls = mock_fetch(lambda *_: json_resp({"symbols": []}))
    await searchMarkets(
        "",
        {
            "country": "US",
            "sector": "Finance",
            "exchange": "NASDAQ",
            "type": "common_stock",
            "offset": 20,
            "fetch": fetch,
        },
    )
    assert query_dict(calls[0]["parsed"]) == {
        "text": "",
        "exchange": "NASDAQ",
        "search_type": "common_stock",
        "start": "20",
        "country": "US",
        "sector": "Finance",
    }


@pytest.mark.asyncio
async def test_search_markets_throws_http_error_for_unexpected_payloads_and_5xx():
    f1, _ = mock_fetch(lambda *_: json_resp({"nope": True}))
    with pytest.raises(Exception) as exc1:
        await searchMarkets("x", {"fetch": f1})
    assert exc1.value.code == "HTTP_ERROR"

    f2, _ = mock_fetch(lambda *_: FetchResponse(status=503, headers=FetchHeaders(), body="down"))
    with pytest.raises(Exception) as exc2:
        await searchMarkets("x", {"fetch": f2})
    assert exc2.value.code == "HTTP_ERROR"
    assert "503" in exc2.value.message


@pytest.mark.asyncio
async def test_search_markets_wraps_network_failures():
    async def bad_fetch(*_):
        raise TypeError("fetch failed")

    with pytest.raises(Exception) as exc_info:
        await searchMarkets("x", {"fetch": bad_fetch})
    assert exc_info.value.code == "HTTP_ERROR"
    assert exc_info.value.message == "fetch failed"


@pytest.mark.asyncio
async def test_get_technical_analysis():
    def route(_p, init, _u):
        body = json.loads(init["body"])
        return json_resp(
            {
                "data": [
                    {
                        "s": "BINANCE:BTCUSD",
                        "d": [(i % 3) / 4 - 0.25 for i in range(len(body["columns"]))],
                    }
                ]
            }
        )

    fetch, calls = mock_fetch(route)
    ta = await getTechnicalAnalysis("BINANCE:BTCUSD", {"fetch": fetch})
    body = json.loads(calls[0]["init"]["body"])
    assert body["symbols"] == {"tickers": ["BINANCE:BTCUSD"]}
    assert body["columns"][:3] == ["Recommend.Other|1", "Recommend.All|1", "Recommend.MA|1"]
    assert "Recommend.All" in body["columns"]
    assert list(ta.keys()) == ["1", "5", "15", "60", "240", "1D", "1W", "1M"]
    assert ta["1D"] == {"Other": -0.5, "All": 0, "MA": 0.5}

    f_empty, _ = mock_fetch(lambda *_: json_resp({"data": []}))
    assert await getTechnicalAnalysis("X", {"fetch": f_empty}) is None


@pytest.mark.asyncio
async def test_indicators_search_and_load():
    def built_in(name):
        return {
            "scriptIdPart": f"STD;{name}",
            "version": 1,
            "scriptName": name,
            "userId": 7,
            "extra": {"kind": "study", "shortDescription": name},
        }

    def route(parsed, _init, _url):
        q = query_dict(parsed)
        if parsed.path.endswith("/list"):
            flt = q.get("filter")
            return json_resp(
                [built_in("Relative Strength Index"), built_in("MACD")]
                if flt == "standard"
                else []
            )
        return json_resp(
            {
                "results": [
                    {
                        "scriptIdPart": "PUB;abc",
                        "version": 2,
                        "scriptName": "My RSI",
                        "author": {"id": 3, "username": "bob"},
                        "imageUrl": "img",
                        "access": 3,
                        "scriptSource": "",
                        "extra": {"kind": "strategy"},
                    }
                ]
            }
        )

    fetch, calls = mock_fetch(route)
    results = await searchIndicators("relative strength", {"fetch": fetch})
    assert [
        query_dict(c["parsed"]).get("filter") or query_dict(c["parsed"]).get("search")
        for c in calls
    ] == ["standard", "candlestick", "fundamental", "relative strength"]
    assert results == [
        {
            "id": "STD;Relative Strength Index",
            "version": "1",
            "name": "Relative Strength Index",
            "author": {"id": 7, "username": "@TRADINGVIEW@"},
            "image": "",
            "source": "",
            "type": "study",
            "access": "closed_source",
        },
        {
            "id": "PUB;abc",
            "version": "2",
            "name": "My RSI",
            "author": {"id": 3, "username": "bob"},
            "image": "img",
            "source": "",
            "type": "strategy",
            "access": "invite_only",
        },
    ]

    f_ind, ind_calls = mock_fetch(
        lambda *_: json_resp(
            {
                "success": True,
                "result": {
                    "ilTemplate": "IL",
                    "metaInfo": {
                        "scriptIdPart": "STD;Supertrend%Strategy",
                        "description": "Supertrend Strategy",
                        "shortDescription": "ST",
                        "pine": {"version": "5.0"},
                        "inputs": [],
                        "styles": {},
                        "plots": [],
                    },
                },
            }
        )
    )
    indicator = await getIndicator(
        "STD;Supertrend%Strategy",
        {"version": "5.0", "credentials": {"session": "s"}, "fetch": f_ind},
    )
    assert (
        ind_calls[0]["url"]
        == "https://pine-facade.tradingview.com/pine-facade/translate/STD;Supertrend%25Strategy/5.0"
    )
    assert ind_calls[0]["init"]["headers"]["cookie"] == "sessionid=s"
    assert indicator.description == "Supertrend Strategy"

    f_nf, _ = mock_fetch(lambda *_: json_resp({"success": False, "reason": "not found"}))
    with pytest.raises(Exception) as exc_nf:
        await getIndicator("STD;XXXXXXX", {"fetch": f_nf})
    assert exc_nf.value.code == "NOT_FOUND"
    assert exc_nf.value.message == 'Inexistent or unsupported indicator: "not found"'

    f_priv, priv_calls = mock_fetch(
        lambda *_: json_resp(
            [
                {
                    "scriptIdPart": "USER;1",
                    "version": 4,
                    "scriptName": "Mine",
                    "imageUrl": "",
                    "scriptSource": "src",
                }
            ]
        )
    )
    priv_list = await getPrivateIndicators({"session": "s", "signature": "g"}, {"fetch": f_priv})
    assert query_dict(priv_calls[0]["parsed"]).get("filter") == "saved"
    assert priv_calls[0]["init"]["headers"]["cookie"] == "sessionid=s;sessionid_sign=g"
    assert priv_list == [
        {
            "id": "USER;1",
            "version": "4",
            "name": "Mine",
            "author": {"id": -1, "username": "@ME@"},
            "image": "",
            "source": "src",
            "type": "study",
            "access": "private",
        }
    ]
    f_bad, _ = mock_fetch(lambda *_: json_resp({"detail": "no"}))
    with pytest.raises(Exception) as exc_auth:
        await getPrivateIndicators({"session": "bad"}, {"fetch": f_bad})
    assert exc_auth.value.code == "AUTH_ERROR"


@pytest.mark.asyncio
async def test_accounts_get_user_and_login_user():
    page = (
        '<script>window.user = {"id":42,"username":"alice","first_name":"Alice","last_name":"L",'
        '"reputation":1.5,"following":3,"followers":4,'
        '"notification_count":{"following":5,"user":6},"session_hash":"h","private_channel":"pc",'
        '"auth_token":"tok","date_joined":"2020-01-02T03:04:05Z"}</script>'
    )
    fetch, calls = mock_fetch(
        lambda parsed, *_: FetchResponse(
            status=302,
            headers=FetchHeaders({"location": "https://fr.tradingview.com/"}),
            body="",
        )
        if parsed.hostname == "www.tradingview.com"
        else FetchResponse(status=200, headers=FetchHeaders(), body=page)
    )
    user = await getUser({"session": "s", "signature": "g"}, {"fetch": fetch})
    assert [c["parsed"].hostname for c in calls] == ["www.tradingview.com", "fr.tradingview.com"]
    assert calls[0]["init"]["redirect"] == "manual"
    assert user == {
        "id": 42,
        "username": "alice",
        "firstName": "Alice",
        "lastName": "L",
        "reputation": 1.5,
        "following": 3,
        "followers": 4,
        "notifications": {"following": 5, "user": 6},
        "session": "s",
        "signature": "g",
        "sessionHash": "h",
        "privateChannel": "pc",
        "authToken": "tok",
        "joinDate": datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    }

    f_empty_notif, _ = mock_fetch(
        lambda *_: FetchResponse(
            status=200,
            headers=FetchHeaders(),
            body=page.replace('"notification_count":{"following":5,"user":6}', '"notification_count":{}'),
        )
    )
    u2 = await getUser({"session": "s"}, {"fetch": f_empty_notif})
    assert u2["notifications"] == {"following": 0, "user": 0}
    assert u2["authToken"] == "tok"

    no_tok_f, no_tok_calls = mock_fetch(
        lambda *_: FetchResponse(
            status=200,
            headers=FetchHeaders({"location": "https://fr.tradingview.com/chart/"}),
            body="no token",
        )
    )
    with pytest.raises(Exception) as exc_nt:
        await getUser({"session": "s"}, {"fetch": no_tok_f})
    assert exc_nt.value.code == "AUTH_ERROR"
    assert exc_nt.value.message == "Wrong or expired sessionid/signature"
    assert [c["parsed"].path for c in no_tok_calls] == ["/chart/"]

    loop_f, loop_calls = mock_fetch(
        lambda parsed, *_: FetchResponse(
            status=302,
            headers=FetchHeaders(
                {
                    "location": "https://www.tradingview.com/accounts/signin/"
                    if parsed.path == "/"
                    else "https://www.tradingview.com/"
                }
            ),
            body="",
        )
    )
    with pytest.raises(Exception, match="Too many redirects"):
        await getUser({"session": "s"}, {"fetch": loop_f})
    assert len(loop_calls) == 6

    with pytest.raises(Exception) as exc_empty:
        await getUser({"session": ""})
    assert exc_empty.value.code == "INVALID_ARGUMENT"

    evil_f, evil_calls = mock_fetch(
        lambda *_: FetchResponse(
            status=302,
            headers=FetchHeaders({"location": "https://tradingview.com.evil.example/collect"}),
            body="",
        )
    )
    with pytest.raises(Exception) as exc_evil:
        await getUser({"session": "secret"}, {"fetch": evil_f})
    assert exc_evil.value.code == "AUTH_ERROR"
    assert len(evil_calls) == 1

    init_f, init_calls = mock_fetch(
        lambda *_: FetchResponse(status=200, headers=FetchHeaders(), body=page)
    )
    with pytest.raises(Exception) as exc_init:
        await getUser(
            {"session": "secret"},
            {"location": "http://www.tradingview.com/", "fetch": init_f},
        )
    assert exc_init.value.code == "AUTH_ERROR"
    assert len(init_calls) == 0

    login_f, login_calls = mock_fetch(
        lambda *_: json_resp(
            {
                "user": {
                    "id": 1,
                    "username": "bob",
                    "first_name": "B",
                    "last_name": "",
                    "reputation": 0,
                    "following": 0,
                    "followers": 0,
                    "notification_count": {"user": 1, "following": 2},
                    "session_hash": "h",
                    "private_channel": "p",
                    "auth_token": "t",
                    "date_joined": "2021-01-01",
                }
            },
            headers=[
                ("set-cookie", "sessionid=abc; Path=/; HttpOnly"),
                ("set-cookie", "sessionid_sign=def; Path=/"),
            ],
        )
    )
    logged_in = await loginUser({"username": "bob@x.com", "password": "p&ss=1", "fetch": login_f})
    assert login_calls[0]["init"]["body"] == "username=bob%40x.com&password=p%26ss%3D1&remember=on"
    assert login_calls[0]["init"]["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert logged_in["id"] == 1
    assert logged_in["session"] == "abc"
    assert logged_in["signature"] == "def"
    assert logged_in["authToken"] == "t"
    assert logged_in["notifications"] == {"user": 1, "following": 2}

    no_rem_f, no_rem_calls = mock_fetch(
        lambda *_: json_resp({"error": "Invalid username or password"})
    )
    with pytest.raises(Exception) as exc_nr:
        await loginUser({"username": "a", "password": "b", "remember": False, "fetch": no_rem_f})
    assert exc_nr.value.code == "AUTH_ERROR"
    assert exc_nr.value.message == "Invalid username or password"
    assert no_rem_calls[0]["init"]["body"] == "username=a&password=b"


@pytest.mark.asyncio
async def test_layouts_get_chart_token_and_drawings():
    fetch, calls = mock_fetch(lambda *_: json_resp({"token": "jwt"}))
    assert await getChartToken("AbCd", {"fetch": fetch}) == "jwt"
    assert query_dict(calls[0]["parsed"]) == {"image_url": "AbCd", "user_id": "-1"}
    assert "cookie" not in (calls[0]["init"].get("headers") or {})
    await getChartToken(
        "AbCd",
        {"fetch": fetch, "userId": 9, "credentials": {"session": "s", "signature": "g"}},
    )
    assert query_dict(calls[1]["parsed"])["user_id"] == "9"
    assert calls[1]["init"]["headers"]["cookie"] == "sessionid=s;sessionid_sign=g"
    f_bad, _ = mock_fetch(lambda *_: json_resp({}))
    with pytest.raises(Exception) as exc_bad:
        await getChartToken("bad", {"fetch": f_bad})
    assert exc_bad.value.code == "NOT_FOUND"

    f_dwg, dwg_calls = mock_fetch(
        lambda parsed, *_: json_resp({"token": "jwt"})
        if parsed.path == "/chart-token"
        else json_resp(
            {
                "payload": {
                    "sources": {
                        "a": {
                            "id": "a",
                            "symbol": "BINANCE:BTCEUR",
                            "type": "LineToolTrendLine",
                            "state": {"text": "hi", "color": "red"},
                        }
                    }
                }
            }
        )
    )
    drawings = await getDrawings(
        "AbCd", {"symbol": "BINANCE:BTCEUR", "chartId": "1", "fetch": f_dwg}
    )
    assert (
        dwg_calls[1]["url"]
        == "https://charts-storage.tradingview.com/charts-storage/get/layout/AbCd/sources?chart_id=1&jwt=jwt&symbol=BINANCE%3ABTCEUR"
    )
    assert drawings == [
        {
            "id": "a",
            "symbol": "BINANCE:BTCEUR",
            "type": "LineToolTrendLine",
            "state": {"text": "hi", "color": "red"},
            "text": "hi",
            "color": "red",
        }
    ]
    f_np, _ = mock_fetch(
        lambda parsed, *_: json_resp({"token": "jwt"})
        if parsed.path == "/chart-token"
        else json_resp({})
    )
    with pytest.raises(Exception) as exc_np:
        await getDrawings("AbCd", {"fetch": f_np})
    assert exc_np.value.code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_pine_permission_manager():
    with pytest.raises(Exception, match="Pine ID"):
        PinePermissionManager("", {"credentials": {"session": "s", "signature": "g"}})
    with pytest.raises(Exception, match="signature"):
        PinePermissionManager("PUB;1", {"credentials": {"session": "s"}})

    fetch, calls = mock_fetch(
        lambda parsed, *_: json_resp({"results": [{"id": 1, "username": "bob"}]})
        if parsed.path.endswith("list_users/")
        else json_resp({"status": "exists" if "add" in parsed.path else "ok"})
    )
    manager = PinePermissionManager(
        "PUB;abc", {"credentials": {"session": "s", "signature": "g"}, "fetch": fetch}
    )
    expiration = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert await manager.getUsers(5, "user__username") == [{"id": 1, "username": "bob"}]
    assert await manager.addUser("bob", expiration) == "exists"
    assert await manager.modifyExpiration("bob") == "ok"
    assert await manager.removeUser("bob") == "ok"

    assert [
        c["parsed"].path + (f"?{c['parsed'].query}" if c["parsed"].query else "")
        for c in calls
    ] == [
        "/pine_perm/list_users/?limit=5&order_by=user__username",
        "/pine_perm/add/",
        "/pine_perm/modify_user_expiration/",
        "/pine_perm/remove/",
    ]
    assert (
        calls[1]["init"]["body"]
        == "pine_id=PUB%3Babc&username_recip=bob&expiration=2030-01-01T00%3A00%3A00.000Z"
    )
    assert calls[2]["init"]["body"] == "pine_id=PUB%3Babc&username_recip=bob"
    assert calls[0]["init"]["headers"]["cookie"] == "sessionid=s;sessionid_sign=g"
    assert calls[0]["init"]["headers"]["origin"] == "https://www.tradingview.com"

    f_err, _ = mock_fetch(lambda *_: json_resp({"detail": "You are not the owner"}, status=403))
    m_err = PinePermissionManager(
        "PUB;abc", {"credentials": {"session": "s", "signature": "g"}, "fetch": f_err}
    )
    with pytest.raises(Exception) as exc_err:
        await m_err.getUsers()
    assert exc_err.value.code == "HTTP_ERROR"
    assert exc_err.value.message == "You are not the owner"


@pytest.mark.asyncio
async def test_http_response_body_failures_and_account_token_validation():
    failure = RuntimeError("response stream reset")

    class FailingResponse:
        status = 200
        status_text = "OK"
        headers = FetchHeaders()

        async def text(self):
            raise failure

    async def f_fail(*_):
        return FailingResponse()

    with pytest.raises(Exception) as exc1:
        await searchMarkets("BTC", {"fetch": f_fail})
    assert exc1.value.code == "HTTP_ERROR"
    assert exc1.value.cause is failure

    abort_err = AbortError("body cancelled")

    class AbortingResponse:
        status = 200
        status_text = "OK"
        headers = FetchHeaders()

        async def text(self):
            raise abort_err

    async def f_abort(*_):
        return AbortingResponse()

    with pytest.raises(Exception) as exc2:
        await searchMarkets("BTC", {"fetch": f_abort})
    assert exc2.value.code == "ABORTED"
    assert exc2.value.cause is abort_err

    for page_body, st in [
        ("auth_token is unavailable", 200),
        ('{"auth_token":""}', 200),
        ('{"auth_token":"unexpected"}', 403),
    ]:
        f_tok, _ = mock_fetch(
            lambda *_, pb=page_body, s=st: FetchResponse(status=s, headers=FetchHeaders(), body=pb)
        )
        with pytest.raises(Exception) as exc_tok:
            await getUser({"session": "fixture"}, {"fetch": f_tok})
        assert exc_tok.value.code == "AUTH_ERROR"
