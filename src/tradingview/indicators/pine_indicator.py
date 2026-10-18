from __future__ import annotations

import copy
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from .builtin_indicator import _js_typeof

PineInputType = str
PineInput = AttrDict
PineStudyType = str
PineIndicatorDefinition = dict[str, Any]

_INPUT_TYPES: dict[str, str] = {
    "bool": "boolean",
    "integer": "number",
    "float": "number",
    "text": "string",
}


class PineIndicator:
    """A Pine script (built-in, public, invite-only or private) ready to run on a chart."""

    def __init__(self, definition: dict[str, Any] | Any) -> None:
        defn = AttrDict(definition) if isinstance(definition, dict) else definition
        self.id: str = str(defn.id or "")
        self.version: str = str(defn.version or "")
        self.description: str = str(defn.description or "")
        self.short_description: str = str(
            defn.shortDescription if defn.shortDescription is not None else (defn.short_description or "")
        )
        self.shortDescription: str = self.short_description
        self.inputs: AttrDict = AttrDict(copy.deepcopy(dict(defn.inputs or {})))
        self.plots: dict[str, str] = dict(defn.plots or {})
        self.script: str = str(defn.script or "")
        self._type: str = str(defn.get("type") or "Script@tv-scripting-101!")

    @property
    def type(self) -> str:
        return self._type

    def set_type(self, study_type: str) -> PineIndicator:
        """Changes the study type, for example to run a strategy as `StrategyScript`."""
        self._type = study_type
        return self

    setType = set_type

    def find_input(self, key: str | int) -> str | None:
        """Finds the input ID for an input ID (`in_0`), its number (`0`), inline name or internal ID."""
        if f"in_{key}" in self.inputs:
            return f"in_{key}"
        str_key = str(key)
        if str_key in self.inputs:
            return str_key
        for input_id, inp in self.inputs.items():
            if inp.get("inline") == key or inp.get("internalID") == key:
                return input_id
        return None

    findInput = find_input

    def set_input(self, key: str | int, value: Any) -> PineIndicator:
        """Changes an input value, with type and option validation."""
        input_id = self.find_input(key)
        if not input_id:
            raise TradingViewError("INVALID_ARGUMENT", f"Input '{key}' not found")
        inp = self.inputs[input_id]

        expected = _INPUT_TYPES.get(inp["type"])
        if expected and _js_typeof(value) != expected:
            raise TradingViewError("INVALID_ARGUMENT", f"Input '{inp['name']}' ({input_id}) must be a {expected}")
        options = inp.get("options")
        if options is not None and value not in options:
            allowed = ", ".join(str(o) for o in options)
            raise TradingViewError(
                "INVALID_ARGUMENT",
                f"Input '{inp['name']}' ({input_id}) must be one of: {allowed}",
                {"details": options},
            )
        inp["value"] = value
        return self

    setInput = set_input

    def set_inputs(self, values: dict[str, Any]) -> PineIndicator:
        """Changes several inputs at once."""
        for k, v in values.items():
            self.set_input(k, v)
        return self

    setInputs = set_inputs

    def clone(self) -> PineIndicator:
        """Independent copy, so one definition can run with different inputs."""
        return PineIndicator(
            {
                "id": self.id,
                "version": self.version,
                "description": self.description,
                "shortDescription": self.shortDescription,
                "inputs": self.inputs,
                "plots": self.plots,
                "script": self.script,
                "type": self._type,
            }
        )

    def to_study_inputs(self) -> dict[str, Any]:
        """Parameters sent with `create_study` / `modify_study`."""
        out: dict[str, Any] = {"text": self.script}
        if self.id:
            out["pineId"] = self.id
        if self.version:
            out["pineVersion"] = self.version

        for index, (input_id, inp) in enumerate(self.inputs.items()):
            out[input_id] = {
                "v": inp["value"] if inp["type"] != "color" else index,
                "f": inp["isFake"],
                "t": inp["type"],
            }
        return out

    toStudyInputs = to_study_inputs
