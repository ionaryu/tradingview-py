from __future__ import annotations

import json
import re
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from ..events import Emitter
from ..indicators.builtin_indicator import BuiltInIndicator
from ..indicators.pine_indicator import PineIndicator
from ..protocol.compression import decode_compressed
from ..protocol.ids import create_session_id
from .graphics import GraphicsData, RawGraphics, apply_graphics_commands, parse_graphics
from .strategy import StrategyReport, merge_strategy_report

StudyValue = AttrDict
StudyChange = str
StudyEvents = dict[str, Any]
StudyBridge = dict[str, Any] | Any


def _assert_indicator(indicator: Any) -> None:
    if not isinstance(indicator, (PineIndicator, BuiltInIndicator)):
        raise TradingViewError(
            "INVALID_ARGUMENT",
            "The indicator must be a PineIndicator (see getIndicator) or a BuiltInIndicator",
        )


def _study_error_message(error: Any) -> str:
    if isinstance(error, dict) and "error" in error:
        template = error.get("error")
        ctx = error.get("ctx")
        if isinstance(template, str):
            return re.sub(
                r"\{(\w+)\}",
                lambda m: str(ctx[m.group(1)]) if isinstance(ctx, dict) and m.group(1) in ctx else m.group(0),
                template,
            )
    return error if isinstance(error, str) else json.dumps(error)


class Study(Emitter):
    """An indicator running on a chart. Create it with `chart.create_study(indicator)`."""

    def __init__(self, bridge: Any, indicator: PineIndicator | BuiltInIndicator) -> None:
        super().__init__()
        _assert_indicator(indicator)
        self.id: str = create_session_id("st")
        self._bridge = AttrDict(bridge) if isinstance(bridge, dict) else bridge
        self._indicator = indicator
        self._values: dict[int | float, StudyValue] = {}
        self._graphics: RawGraphics = {}
        self._graphic_indexes: list[int] = []
        self._strategy_report: StrategyReport = AttrDict({"trades": [], "history": AttrDict(), "performance": AttrDict()})
        self._removed = False
        self._ready = False

    def create(self) -> None:
        self._bridge.send(
            "create_study",
            [
                self._bridge.chartId,
                self.id,
                "st1",
                "$prices",
                self._indicator.type,
                self._indicator.to_study_inputs(),
            ],
        )

    @property
    def indicator(self) -> PineIndicator | BuiltInIndicator:
        return self._indicator

    @property
    def is_ready(self) -> bool:
        return self._ready

    isReady = is_ready

    @property
    def is_removed(self) -> bool:
        return self._removed

    isRemoved = is_removed

    @property
    def values(self) -> list[StudyValue]:
        return sorted(self._values.values(), key=lambda row: row["$time"])

    @property
    def graphics(self) -> GraphicsData:
        bars_back: dict[int, int] = self._bridge.barsBack()
        mapped = [bars_back.get(idx) for idx in self._graphic_indexes]
        return parse_graphics(self._graphics, mapped)

    @property
    def strategy_report(self) -> StrategyReport:
        return self._strategy_report

    strategyReport = strategy_report

    def set_indicator(self, indicator: PineIndicator | BuiltInIndicator) -> None:
        """Replaces the indicator (typically the same script with new inputs)."""
        _assert_indicator(indicator)
        if self._removed:
            raise TradingViewError("INVALID_STATE", "The study is removed")
        self._indicator = indicator
        self._bridge.send(
            "modify_study",
            [self._bridge.chartId, self.id, "st1", indicator.to_study_inputs()],
        )

    setIndicator = set_indicator

    def remove(self) -> None:
        """Removes the study from the chart. Idempotent."""
        if self._removed:
            return
        self._bridge.send("remove_study", [self._bridge.chartId, self.id])
        self._removed = True
        self._bridge.unregister(self.id)

    def dispose(self, error: TradingViewError | None = None) -> None:
        if self._removed:
            return
        self._removed = True
        if error is not None:
            self._emit("error", error)

    def on_packet(self, packet: dict[str, Any]) -> None:
        self._bridge.log("study", self.id, packet)
        m = packet.get("m")
        if m == "study_loading":
            self._emit("loading")
        elif m == "study_completed":
            self._ready = True
            self._emit("ready")
        elif m == "study_error":
            p_list = packet.get("p") or []
            err_payload = p_list[3] if len(p_list) > 3 else None
            self._emit(
                "error",
                TradingViewError(
                    "STUDY_ERROR",
                    f"Study error: {_study_error_message(err_payload)}",
                    {"details": p_list[3:]},
                ),
            )

    onPacket = on_packet

    def on_data(self, data: Any) -> None:
        if not data or not isinstance(data, dict):
            return
        changes: list[str] = []

        st_rows = data.get("st")
        if isinstance(st_rows, list) and len(st_rows) > 0:
            plots = self._indicator.plots if isinstance(self._indicator, PineIndicator) else None
            for row in st_rows:
                val = AttrDict()
                v_list = row.get("v") or []
                for i, plot_val in enumerate(v_list):
                    if i == 0:
                        val["$time"] = plot_val
                        continue
                    name = plots.get(f"plot_{i - 1}") if plots else None
                    if name and name not in val:
                        val[name] = plot_val
                    else:
                        val[f"plot_{i - 1}"] = plot_val
                self._values[val["$time"]] = val
            changes.append("plots")

        ns = data.get("ns")
        if isinstance(ns, dict) and ns.get("d"):
            parsed = None
            try:
                parsed = json.loads(ns["d"])
            except Exception as err:
                self._emit("error", TradingViewError("PARSE_ERROR", "Unable to parse study data", {"cause": err}))

            if isinstance(parsed, dict):
                if parsed.get("graphicsCmds"):
                    apply_graphics_commands(self._graphics, parsed["graphicsCmds"])
                    changes.append("graphic")

                if parsed.get("dataCompressed"):
                    try:
                        decoded = decode_compressed(parsed["dataCompressed"])
                        if isinstance(decoded, dict) and "report" in decoded:
                            changes.extend(merge_strategy_report(self._strategy_report, decoded.get("report")))
                    except Exception as err:
                        self._emit(
                            "error",
                            TradingViewError(
                                "PARSE_ERROR",
                                "Unable to parse compressed strategy report",
                                {"cause": err},
                            ),
                        )

                raw_data_field = parsed.get("data")
                if isinstance(raw_data_field, dict) and raw_data_field.get("report"):
                    try:
                        changes.extend(merge_strategy_report(self._strategy_report, raw_data_field["report"]))
                    except Exception as err:
                        self._emit(
                            "error",
                            TradingViewError(
                                "PARSE_ERROR",
                                "Unable to parse strategy report",
                                {"cause": err},
                            ),
                        )

        if isinstance(ns, dict) and isinstance(ns.get("indexes"), list):
            self._graphic_indexes = list(ns["indexes"])

        self._emit("update", changes)

    onData = on_data
