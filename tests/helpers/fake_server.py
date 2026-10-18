from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable
from typing import Any

from tradingview._types import AttrDict
from tradingview.protocol.framing import decode_frames, encode_frame


def _schedule(fn: Callable[[], Any]) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon(fn)
    except RuntimeError:
        fn()


class FakeConnection:
    """In-memory websocket connection driven by `FakeServer`."""

    def __init__(self, server: FakeServer, request: dict[str, Any], handlers: dict[str, Any] | Any) -> None:
        self.server = server
        self.request = AttrDict(request)
        self.handlers = AttrDict(handlers) if isinstance(handlers, dict) else handlers
        self.is_open = False
        self.closed = False
        self.terminated = False
        self.sent: list[AttrDict] = []
        self.raw: list[str] = []
        self.heartbeats: list[int] = []
        self._ended = False

    @property
    def isOpen(self) -> bool:
        return self.is_open

    @isOpen.setter
    def isOpen(self, val: bool) -> None:
        self.is_open = val

    def _call_handler(self, name: str, *args: Any) -> None:
        fn = self.handlers.get(name) if isinstance(self.handlers, dict) else getattr(self.handlers, name, None)
        if callable(fn):
            fn(*args)

    def open(self) -> None:
        if self.closed:
            return
        self.is_open = True
        self._call_handler("onOpen")

    def send(self, data: str) -> None:
        if not self.is_open:
            raise RuntimeError("FakeConnection: send while closed")
        self.raw.append(data)
        for frame in decode_frames(data):
            if frame["type"] == "heartbeat":
                self.heartbeats.append(frame["id"])
            if frame["type"] != "packet":
                continue
            packet = AttrDict({"m": frame["packet"]["m"], "p": list(frame["packet"]["p"])})
            self.sent.append(packet)
            self.server.handle(self, packet)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.is_open = False
        _schedule(lambda: self._end(1000, ""))

    def terminate(self) -> None:
        self.terminated = True
        self.closed = True
        self.is_open = False
        _schedule(lambda: self._end(1006, ""))

    def _end(self, code: int, reason: str) -> None:
        if self._ended:
            return
        self._ended = True
        self._call_handler("onClose", code, reason)

    def push(self, *payloads: dict[str, Any] | str) -> None:
        if self.closed:
            return
        msg = "".join(encode_frame(p) for p in payloads)
        self._call_handler("onMessage", msg)

    def push_later(self, *payloads: dict[str, Any] | str) -> None:
        _schedule(lambda: self.push(*payloads))

    pushLater = push_later

    def drop(self, code: int = 1006, reason: str = "Connection lost") -> None:
        if self.closed:
            return
        self.closed = True
        self.is_open = False
        self._end(code, reason)

    def packets(self, method: str) -> list[AttrDict]:
        return [pkt for pkt in self.sent if pkt["m"] == method]


class FakeServer:
    """Scriptable fake of the TradingView websocket server."""

    def __init__(self, options: dict[str, Any] | None = None, **kwargs: Any) -> None:
        opts = {**(options or {}), **kwargs}
        step = int(opts.get("step", 86_400))
        self.options = AttrDict(
            {
                "history": int(opts.get("history", 1000)),
                "batchLimit": opts.get("batchLimit", opts.get("batch_limit")),
                "endReason": opts.get("endReason", opts.get("end_reason", "end")),
                "step": step,
                "now": int(opts.get("now", (1_800_000_000 // step) * step)),
                "invalidSymbols": list(opts.get("invalidSymbols", opts.get("invalid_symbols", ["XXXXX"]))),
                "studyPlots": int(opts.get("studyPlots", opts.get("study_plots", 1))),
                "studyNs": opts.get("studyNs", opts.get("study_ns")),
                "studyError": opts.get("studyError", opts.get("study_error")),
                "replaySteps": int(opts.get("replaySteps", opts.get("replay_steps", 3))),
            }
        )
        self.connections: list[FakeConnection] = []
        self.auto_open: bool = True
        self.respond: bool = True
        self._handlers: dict[str, Callable[[FakeConnection, AttrDict], Any]] = {}
        self._charts: dict[str, dict[str, Any]] = {}
        self._replay_steps: dict[str, int] = {}

    @property
    def autoOpen(self) -> bool:
        return self.auto_open

    @autoOpen.setter
    def autoOpen(self, val: bool) -> None:
        self.auto_open = val

    def transport(self, request: dict[str, Any], handlers: dict[str, Any] | Any) -> FakeConnection:
        conn = FakeConnection(self, request, handlers)
        self.connections.append(conn)
        if self.auto_open:
            _schedule(conn.open)
        return conn

    @property
    def last(self) -> FakeConnection:
        if not self.connections:
            raise RuntimeError("No connection yet")
        return self.connections[-1]

    def on(self, method: str, handler: Callable[[FakeConnection, AttrDict], Any]) -> None:
        self._handlers[method] = handler

    def bar_time(self, position: int) -> int:
        return int(self.options.now - (self.options.history - 1 - position) * self.options.step)

    barTime = bar_time

    def bar(self, position: int) -> list[int | float]:
        close = 100 + position
        return [self.bar_time(position), close - 1, close + 2, close - 3, close, 10 + position]

    def handle(self, connection: FakeConnection, packet: AttrDict) -> None:
        custom = self._handlers.get(packet["m"])
        if custom is not None and custom(connection, packet) is not False:
            return
        if not self.respond:
            return
        fn = getattr(self, f"on_{packet['m']}", None)
        if callable(fn):
            fn(connection, packet["p"])

    @staticmethod
    def _symbol_of(init: str) -> str:
        parsed = json.loads(init[1:])
        sym = parsed["symbol"]
        return sym if isinstance(sym, str) else sym["symbol"]

    def _prices_update(self, chart: str, from_pos: int, to_pos: int, state: dict[str, Any]) -> dict[str, Any]:
        bars = []
        for pos in range(from_pos, to_pos):
            bars.append({"i": pos - state["firstPosition"], "v": self.bar(pos)})
        return {
            "m": "timescale_update",
            "p": [chart, {"$prices": {"s": bars, "ns": {"d": "", "indexes": []}, "t": "s1"}}, {}],
        }

    def _study_update(self, chart: str, study_id: str, study_type: str, state: dict[str, Any]) -> dict[str, Any]:
        if self.options.studyError is not None:
            return {"m": "study_error", "p": [chart, study_id, "s1_st1", self.options.studyError, "node"]}
        first = self.options.history - state["loaded"]
        rows = []
        for pos in range(first, self.options.history):
            values = [pos + plot / 10 for plot in range(self.options.studyPlots)]
            rows.append({"i": pos - state["firstPosition"], "v": [self.bar_time(pos), *values]})
        ns_fn = self.options.studyNs
        if callable(ns_fn):
            try:
                ns = ns_fn(study_type)
            except TypeError:
                ns = ns_fn()
        else:
            ns = None
        return {
            "m": "du",
            "p": [
                chart,
                {
                    study_id: {
                        "st": rows,
                        "ns": {"d": json.dumps(ns) if ns else "", "indexes": [0, 1, 2] if ns else []},
                    }
                },
            ],
        }

    def _completed(self, chart: str, state: dict[str, Any], status: str = "streaming") -> dict[str, Any]:
        details: dict[str, Any] = {"rt_update_period": 5}
        if state["loaded"] >= self.options.history:
            details["data_completed"] = self.options.endReason
        return {"m": "series_completed", "p": [chart, "$prices", status, "s1", details]}

    def on_chart_create_session(self, _c: FakeConnection, params: list[Any]) -> None:
        chart = params[0]
        self._charts[chart] = {
            "symbols": {},
            "loaded": 0,
            "firstPosition": 0,
            "studies": {},
        }

    def on_resolve_symbol(self, c: FakeConnection, params: list[Any]) -> None:
        chart, series_id, init = params[0], params[1], params[2]
        state = self._charts.get(chart)
        if not state:
            return
        symbol = self._symbol_of(init)
        if symbol in self.options.invalidSymbols:
            c.push_later({"m": "symbol_error", "p": [chart, series_id, "invalid symbol"]})
            return
        state["symbols"][series_id] = symbol
        c.push_later(
            {
                "m": "symbol_resolved",
                "p": [
                    chart,
                    series_id,
                    {
                        "name": symbol.split(":")[-1],
                        "full_name": symbol,
                        "pro_name": symbol,
                        "description": f"Fake {symbol}",
                        "exchange": symbol.split(":")[0],
                        "currency_code": "EUR",
                        "type": "spot",
                        "pricescale": 100,
                        "minmov": 1,
                        "timezone": "Etc/UTC",
                        "session": "24x7",
                        "has_intraday": True,
                        "fractional": False,
                        "is_tradable": True,
                    },
                ],
            }
        )

    def on_create_series(self, c: FakeConnection, params: list[Any]) -> None:
        chart, series_id, rng = params[0], params[3], params[5]
        state = self._charts.get(chart)
        if not state or series_id not in state["symbols"]:
            return
        count = abs(rng[2]) if isinstance(rng, list) else int(rng)
        batch_limit = self.options.batchLimit if self.options.batchLimit is not None else math.inf
        state["seriesId"] = series_id
        state["loaded"] = int(min(count, self.options.history, batch_limit))
        state["firstPosition"] = int(self.options.history - state["loaded"])
        c.push_later(
            {"m": "series_loading", "p": [chart, "$prices", "s1"]},
            self._prices_update(chart, state["firstPosition"], self.options.history, state),
            self._completed(chart, state),
        )

    def on_modify_series(self, c: FakeConnection, params: list[Any]) -> None:
        chart, series_id = params[0], params[3]
        state = self._charts.get(chart)
        if not state or series_id not in state["symbols"]:
            return
        c.push_later(
            self._prices_update(chart, self.options.history - state["loaded"], self.options.history, state),
            self._completed(chart, state),
        )

    def on_request_more_data(self, c: FakeConnection, params: list[Any]) -> None:
        chart, count = params[0], int(params[2])
        state = self._charts.get(chart)
        if not state:
            return
        batch_limit = self.options.batchLimit if self.options.batchLimit is not None else math.inf
        add = int(max(0, min(count, batch_limit, self.options.history - state["loaded"])))
        first = int(self.options.history - state["loaded"] - add)
        end = int(self.options.history - state["loaded"])
        state["loaded"] += add
        payloads: list[dict[str, Any]] = [{"m": "series_loading", "p": [chart, "$prices", "s1"]}]
        if add > 0:
            payloads.append(self._prices_update(chart, first, end, state))
        for study_id, study_type in state["studies"].items():
            payloads.extend(
                [
                    {"m": "study_loading", "p": [chart, study_id, "s1_st1"]},
                    self._study_update(chart, study_id, study_type, state),
                    {"m": "study_completed", "p": [chart, study_id, "s1_st1"]},
                ]
            )
        payloads.append(self._completed(chart, state))
        c.push_later(*payloads)

    def on_create_study(self, c: FakeConnection, params: list[Any]) -> None:
        chart, study_id, study_type = params[0], params[1], params[4]
        state = self._charts.get(chart)
        if not state:
            return
        state["studies"][study_id] = study_type
        update = self._study_update(chart, study_id, study_type, state)
        payloads = [{"m": "study_loading", "p": [chart, study_id, "s1_st1"]}, update]
        if update["m"] != "study_error":
            payloads.append({"m": "study_completed", "p": [chart, study_id, "s1_st1"]})
        c.push_later(*payloads)

    def on_quote_add_symbols(self, c: FakeConnection, params: list[Any]) -> None:
        session, keys = params[0], params[1:]
        for key in keys:
            symbol = json.loads(key[1:])["symbol"] if key.startswith("=") else key
            if symbol in self.options.invalidSymbols:
                c.push_later({"m": "qsd", "p": [session, {"n": key, "s": "error", "errmsg": "no_such_symbol", "v": {}}]})
                continue
            c.push_later(
                {
                    "m": "qsd",
                    "p": [
                        session,
                        {
                            "n": key,
                            "s": "ok",
                            "v": {"lp": 100, "ch": 1, "description": f"Fake {symbol}", "currency_code": "EUR"},
                        },
                    ],
                },
                {"m": "quote_completed", "p": [session, key]},
            )

    def on_replay_add_series(self, c: FakeConnection, params: list[Any]) -> None:
        replay, req = params[0], params[1]
        c.push_later({"m": "replay_ok", "p": [replay, req]})

    def on_replay_reset(self, c: FakeConnection, params: list[Any]) -> None:
        replay, req, tm = params[0], params[1], params[2]
        self._replay_steps[replay] = 0
        c.push_later(
            {"m": "replay_instance_id", "p": [replay, "replay-instance-1"]},
            {"m": "replay_ok", "p": [replay, req]},
            {"m": "replay_point", "p": [replay, tm]},
            {"m": "replay_resolutions", "p": [replay, "1D", "1S"]},
        )

    def on_replay_step(self, c: FakeConnection, params: list[Any]) -> None:
        replay, req, count = params[0], params[1], int(params[2])
        steps = self._replay_steps.get(replay, 0) + count
        self._replay_steps[replay] = steps
        payloads: list[dict[str, Any]] = [
            {"m": "replay_ok", "p": [replay, req]},
            {"m": "replay_point", "p": [replay, self.bar_time(steps)]},
        ]
        if steps >= self.options.replaySteps:
            payloads.append({"m": "replay_data_end", "p": [replay]})
        c.push_later(*payloads)

    def on_replay_start(self, c: FakeConnection, params: list[Any]) -> None:
        replay, req = params[0], params[1]
        c.push_later({"m": "replay_ok", "p": [replay, req]})

    def on_replay_stop(self, c: FakeConnection, params: list[Any]) -> None:
        replay, req = params[0], params[1]
        c.push_later({"m": "replay_ok", "p": [replay, req]})


async def flush(rounds: int = 3) -> None:
    """Waits for pending callbacks/tasks."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def until(predicate: Callable[[], bool], timeout_ms: int = 2000) -> None:
    """Polls until `predicate()` returns True."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("until: timed out")
        await asyncio.sleep(0.002)
