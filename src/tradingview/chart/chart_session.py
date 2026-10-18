from __future__ import annotations

import asyncio
import json
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from ..events import Emitter
from ..protocol.ids import create_session_id
from .study import Study
from .types import CHART_TYPE_STUDIES, Candle, SymbolInfo

MarketOptions = dict[str, Any]
SeriesCompletedInfo = AttrDict
ChartEvents = dict[str, Any]


class ChartSession(Emitter):
    """A chart: one symbol series plus any number of studies, with optional replay mode."""

    def __init__(self, client: Any) -> None:
        super().__init__()
        self.id: str = create_session_id("cs")
        self.replay_id: str = create_session_id("rs")
        self.replayId: str = self.replay_id
        self.client = client
        self._candles: dict[int | float, Candle] = {}
        self._bar_indexes: dict[int, int | float] = {}
        self._studies: dict[str, Study] = {}
        self._replay_requests: dict[str, asyncio.Future[None]] = {}
        self._symbol_info: SymbolInfo | None = None
        self._series_count: int = 0
        self._series_created: bool = False
        self._turnaround: int = 0
        self._timeframe: str = "D"
        self._replay_mode: bool = False
        self._deleted: bool = False

        client.register_session(
            self.id,
            {
                "onPacket": self._on_chart_packet,
                "onClose": self._on_client_close,
            },
        )
        client.register_session(self.replay_id, {"onPacket": self._on_replay_packet})
        client.send("chart_create_session", [self.id])

    @property
    def candles(self) -> list[Candle]:
        return sorted(self._candles.values(), key=lambda c: c["time"])

    @property
    def last_candle(self) -> Candle | None:
        if not self._candles:
            return None
        max_time = max(self._candles.keys())
        return self._candles[max_time]

    lastCandle = last_candle

    @property
    def symbol_info(self) -> SymbolInfo | None:
        return self._symbol_info

    symbolInfo = symbol_info

    @property
    def timeframe(self) -> str:
        return self._timeframe

    @property
    def series_id(self) -> str | None:
        return f"ser_{self._series_count}" if self._series_count else None

    seriesId = series_id

    @property
    def is_replay(self) -> bool:
        return self._replay_mode

    isReplay = is_replay

    @property
    def is_deleted(self) -> bool:
        return self._deleted

    isDeleted = is_deleted

    @property
    def studies(self) -> list[Study]:
        return list(self._studies.values())

    def set_market(self, symbol: str, options: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Loads a symbol, optionally with a custom bar type or in replay mode."""
        self._assert_alive()
        if not symbol:
            raise TradingViewError("INVALID_ARGUMENT", "A symbol is required")
        opts = {**(options or {}), **kwargs}
        self._candles.clear()
        self._bar_indexes.clear()
        self._symbol_info = None
        timeframe = str(opts.get("timeframe") or "D")

        if self._replay_mode:
            self._replay_mode = False
            self._reject_replay_requests(TradingViewError("INVALID_STATE", "Replay session replaced"))
            self.client.send("replay_delete_session", [self.replay_id])

        symbol_init: dict[str, Any] = {
            "symbol": symbol,
            "adjustment": opts.get("adjustment") or "splits",
        }
        if opts.get("backAdjustment") or opts.get("back_adjustment"):
            symbol_init["backadjustment"] = "default"
        if opts.get("session"):
            symbol_init["session"] = opts["session"]
        if opts.get("currency"):
            symbol_init["currency-id"] = opts["currency"]

        replay_ts = opts.get("replay")
        if replay_ts is not None:
            self._replay_mode = True
            self.client.send("replay_create_session", [self.replay_id])
            self.client.send(
                "replay_add_series",
                [
                    self.replay_id,
                    "req_replay_addseries",
                    "=" + json.dumps(symbol_init, separators=(",", ":")),
                    timeframe,
                ],
            )
            self.client.send("replay_reset", [self.replay_id, "req_replay_reset", replay_ts])

        chart_init: dict[str, Any] = symbol_init
        chart_type = opts.get("type")
        if chart_type or replay_ts is not None:
            chart_init = {"symbol": symbol_init}
            if replay_ts is not None:
                chart_init["replay"] = self.replay_id
            if chart_type:
                study_type = CHART_TYPE_STUDIES.get(chart_type)
                if not study_type:
                    raise TradingViewError("INVALID_ARGUMENT", f"Unknown chart type '{chart_type}'")
                chart_init["type"] = study_type
                chart_init["inputs"] = dict(opts.get("inputs") or {})

        self._series_count += 1
        self.client.send(
            "resolve_symbol",
            [self.id, f"ser_{self._series_count}", "=" + json.dumps(chart_init, separators=(",", ":"))],
        )
        count = int(opts.get("count", 100))
        self._send_series(timeframe, count, opts.get("to"))

    setMarket = set_market

    def set_timeframe(self, timeframe: str) -> None:
        """Changes the timeframe of the loaded symbol, keeping studies."""
        self._assert_alive()
        if not self._series_count:
            raise TradingViewError("INVALID_STATE", "Please set the market before setting the timeframe")
        self._candles.clear()
        self._bar_indexes.clear()
        self._send_series(timeframe, 100)

    setTimeframe = set_timeframe

    def _send_series(self, timeframe: str, count: int, to: int | float | None = None) -> None:
        self._timeframe = timeframe
        self._turnaround += 1
        rng: Any = count if to is None else ["bar_count", to, count]
        self.client.send(
            "modify_series" if self._series_created else "create_series",
            [
                self.id,
                "$prices",
                f"s{self._turnaround}",
                f"ser_{self._series_count}",
                timeframe,
                "" if self._series_created else rng,
            ],
        )
        self._series_created = True

    def set_timezone(self, timezone: str) -> None:
        """Changes the chart timezone."""
        self._assert_alive()
        self.client.send("switch_timezone", [self.id, timezone])

    setTimezone = set_timezone

    def fetch_more(self, count: int = 1) -> None:
        """Loads more history."""
        self._assert_alive()
        self.client.send("request_more_data", [self.id, "$prices", count])

    fetchMore = fetch_more

    async def replay_step(self, count: int = 1) -> None:
        """Moves the replay forward by `count` bars."""
        await self._replay_request("replay_step", "rsq_step", [count])

    replayStep = replay_step

    async def replay_start(self, interval_ms: int = 1000) -> None:
        """Plays the replay automatically, one bar every `interval_ms`."""
        await self._replay_request("replay_start", "rsq_start", [interval_ms])

    replayStart = replay_start

    async def replay_stop(self) -> None:
        """Pauses automatic replay."""
        await self._replay_request("replay_stop", "rsq_stop", [])

    replayStop = replay_stop

    async def _replay_request(self, method: str, prefix: str, params: list[Any]) -> None:
        if self._deleted:
            raise TradingViewError("INVALID_STATE", "The chart is deleted")
        if not self._replay_mode:
            raise TradingViewError("INVALID_STATE", "No replay session: use setMarket(symbol, { replay })")
        request_id = create_session_id(prefix)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        self._replay_requests[request_id] = fut
        self.client.send(method, [self.replay_id, request_id, *params])
        await fut

    def create_study(self, indicator: Any) -> Study:
        """Adds a study (Pine or built-in indicator) to this chart."""
        self._assert_alive()
        bridge = {
            "chartId": self.id,
            "send": lambda method, params: self.client.send(method, params),
            "barsBack": self._bars_back,
            "log": lambda *args: self.client.log(*args),
            "unregister": lambda sid: self._studies.pop(sid, None),
        }
        study = Study(bridge, indicator)
        self._studies[study.id] = study
        study.create()
        return study

    createStudy = create_study

    def delete(self) -> None:
        """Deletes the chart (and its replay session). Idempotent."""
        if self._deleted:
            return
        if not self.client.is_closed:
            if self._replay_mode:
                self.client.send("replay_delete_session", [self.replay_id])
            self.client.send("chart_delete_session", [self.id])
        self._dispose(TradingViewError("INVALID_STATE", "The chart was deleted"))

    def _dispose(self, error: TradingViewError, notify: bool = False) -> None:
        self._deleted = True
        self._replay_mode = False
        self.client.unregister_session(self.id)
        self.client.unregister_session(self.replay_id)
        self._reject_replay_requests(error)
        for study in list(self._studies.values()):
            study.dispose(error if notify else None)
        self._studies.clear()

    def _on_client_close(self, error: TradingViewError, expected: bool) -> None:
        if self._deleted:
            return
        self._dispose(error, notify=not expected)
        if not expected:
            self._emit("error", error)

    def _assert_alive(self) -> None:
        if self._deleted:
            raise TradingViewError("INVALID_STATE", "The chart is deleted")

    def _reject_replay_requests(self, error: TradingViewError) -> None:
        for fut in list(self._replay_requests.values()):
            if not fut.done():
                fut.set_exception(error)
        self._replay_requests.clear()

    def _bars_back(self) -> dict[int, int]:
        sorted_entries = sorted(self._bar_indexes.items(), key=lambda kv: kv[1], reverse=True)
        return {idx: pos for pos, (idx, _time) in enumerate(sorted_entries)}

    def _on_chart_packet(self, packet: dict[str, Any]) -> None:
        self.client.log("chart", self.id, packet)
        p_list = packet.get("p") or []
        target = p_list[1] if len(p_list) > 1 else None

        if isinstance(target, str) and target in self._studies:
            self._studies[target].on_packet(packet)
            return

        m = packet.get("m")
        if m == "symbol_resolved":
            raw_info = p_list[2] if len(p_list) > 2 and isinstance(p_list[2], dict) else {}
            self._symbol_info = AttrDict({"series_id": str(target), **raw_info})
            self._emit("symbolLoaded", self._symbol_info)
        elif m in ("timescale_update", "du"):
            data = p_list[1] if len(p_list) > 1 and isinstance(p_list[1], dict) else {}
            changes: list[str] = []
            for key, val in data.items():
                changes.append(key)
                if key == "$prices":
                    self._update_candles(val)
                elif key in self._studies:
                    self._studies[key].on_data(val)
            self._emit("update", changes)
        elif m == "series_loading":
            self._emit("seriesLoading")
        elif m == "series_completed":
            details = p_list[4] if len(p_list) > 4 and isinstance(p_list[4], dict) else {}
            self._emit(
                "seriesCompleted",
                AttrDict(
                    {
                        "status": str(p_list[2] if len(p_list) > 2 and p_list[2] is not None else ""),
                        "dataCompleted": details.get("data_completed"),
                        "turnaround": str(p_list[3] if len(p_list) > 3 and p_list[3] is not None else ""),
                        "raw": p_list,
                    }
                ),
            )
        elif m == "symbol_error":
            msg = p_list[2] if len(p_list) > 2 else ""
            self._emit(
                "error",
                TradingViewError("SYMBOL_ERROR", f"({target}) Symbol error: {msg}", {"details": p_list}),
            )
        elif m == "series_error":
            msg = p_list[3] if len(p_list) > 3 else ""
            self._emit(
                "error",
                TradingViewError("SERIES_ERROR", f"Series error: {msg}", {"details": p_list}),
            )
        elif m == "critical_error":
            msg = p_list[1] if len(p_list) > 1 else ""
            self._emit(
                "error",
                TradingViewError("CRITICAL_ERROR", f"Critical error: {msg}", {"details": p_list}),
            )

    def _update_candles(self, prices: Any) -> None:
        if not isinstance(prices, dict):
            return
        for bar in prices.get("s") or ():
            v = bar.get("v") or []
            if len(v) < 5:
                continue
            tm, o, h, l, c = v[0], v[1], v[2], v[3], v[4]
            vol = v[5] if len(v) > 5 and v[5] is not None else 0
            self._bar_indexes[int(bar["i"])] = tm
            self._candles[tm] = AttrDict(
                {
                    "time": tm,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": vol,
                }
            )

    def _on_replay_packet(self, packet: dict[str, Any]) -> None:
        self.client.log("replay", self.replay_id, packet)
        m = packet.get("m")
        p_list = packet.get("p") or []
        if m == "replay_ok":
            req_id = str(p_list[1]) if len(p_list) > 1 else ""
            fut = self._replay_requests.pop(req_id, None)
            if fut is not None and not fut.done():
                fut.set_result(None)
        elif m == "replay_instance_id":
            self._emit("replayLoaded", str(p_list[1] if len(p_list) > 1 else ""))
        elif m == "replay_point":
            val = p_list[1] if len(p_list) > 1 else 0
            f = float(val)
            self._emit("replayPoint", int(f) if f.is_integer() else f)
        elif m == "replay_resolutions":
            r1 = str(p_list[1] if len(p_list) > 1 else "")
            r2 = str(p_list[2] if len(p_list) > 2 else "")
            self._emit("replayResolution", r1, r2)
        elif m == "replay_data_end":
            self._emit("replayEnd")
        elif m in ("critical_error", "replay_error"):
            msg = p_list[1] if len(p_list) > 1 else ""
            err = TradingViewError("CRITICAL_ERROR", f"Replay error: {msg}", {"details": p_list})
            self._reject_replay_requests(err)
            self._emit("error", err)
