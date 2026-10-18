import time
import pytest

from tradingview.indicators.builtin_indicator import BuiltInIndicator
from tradingview.http.indicators import parseIndicatorDefinition
from tests.helpers.indicators import makePine


def test_pine_indicator_serialises_inputs():
    pine = makePine()
    assert pine.type == "Script@tv-scripting-101!"
    assert pine.toStudyInputs() == {
        "text": "bmI9Ii...IL",
        "pineId": "PUB;test",
        "pineVersion": "3.0",
        "in_0": {"v": 14, "f": False, "t": "integer"},
        "in_1": {"v": "close", "f": False, "t": "source"},
        "in_2": {"v": 2, "f": True, "t": "color"},
        "in_3": {"v": True, "f": False, "t": "bool"},
    }


def test_pine_indicator_finds_inputs_and_validates_values():
    pine = makePine()
    pine.setInput("in_0", 20).setInput(0, 21).setInput("Length", 22).setInput("length", 23)
    assert pine.inputs["in_0"]["value"] == 23
    pine.setInputs({"src": "open", "Show": False})
    assert pine.inputs["in_1"]["value"] == "open"
    with pytest.raises(Exception, match="must be a number"):
        pine.setInput("length", "5")
    with pytest.raises(Exception, match="must be one of: close, open"):
        pine.setInput("src", "hl2")
    with pytest.raises(Exception, match="not found"):
        pine.setInput("missing", 1)


def test_pine_indicator_clones_independently_and_changes_study_type():
    pine = makePine()
    copy = pine.clone().setType("StrategyScript@tv-scripting-101!")
    copy.setInput("length", 99)
    assert pine.inputs["in_0"]["value"] == 14
    assert pine.type == "Script@tv-scripting-101!"
    assert copy.type == "StrategyScript@tv-scripting-101!"


def test_builtin_indicator_starts_from_defaults_and_validates():
    volume = BuiltInIndicator("Volume@tv-basicstudies-241")
    assert volume.toStudyInputs() == {"length": 20, "col_prev_close": False}
    volume.setOption("length", 50)
    with pytest.raises(Exception, match="must be a number"):
        volume.setOption("length", "50")
    with pytest.raises(Exception, match="not allowed"):
        volume.setOption("rows", 1)
    volume.setOption("rows", 1, True)
    assert volume.options["rows"] == 1


def test_builtin_indicator_computes_time_defaults_and_accepts_unknown_types():
    before = int(time.time() * 1000)
    profile = BuiltInIndicator("VbPFixed@tv-basicstudies-241!", {"first_bar_time": 123})
    assert profile.options["last_bar_time"] >= before
    assert profile.options["first_bar_time"] == 123
    custom = BuiltInIndicator("Custom@tv-basicstudies-1", {"anything": "x"})
    assert custom.options == {"anything": "x"}
    with pytest.raises(Exception, match="required"):
        BuiltInIndicator("")


def test_parse_indicator_definition():
    indicator = parseIndicatorDefinition(
        {
            "ilTemplate": "IL",
            "metaInfo": {
                "scriptIdPart": "STD;Test",
                "description": "Test",
                "shortDescription": "T",
                "pine": {"version": "12.0"},
                "inputs": [
                    {"id": "text", "name": "text", "defval": "x", "type": "text"},
                    {"id": "pineId", "name": "pineId", "defval": "x", "type": "text"},
                    {"id": "in_0", "name": "Fast length!", "defval": 9, "type": "integer", "options": None},
                    {
                        "id": "in_1",
                        "name": "Mode",
                        "inline": "mode",
                        "internalID": "modeId",
                        "defval": "A",
                        "type": "text",
                        "options": ["A", "B"],
                        "isHidden": True,
                    },
                ],
                "styles": {
                    "plot_0": {"title": "MA line"},
                    "plot_1": {"title": "MA line"},
                    "plot_2": {"title": "MA line"},
                },
                "plots": [
                    {"id": "plot_3", "type": "colorer", "target": "plot_0"},
                    {"id": "plot_0", "type": "line"},
                ],
            },
        },
        "STD%3BTest",
        "last",
    )
    assert indicator.id == "STD;Test"
    assert indicator.version == "12.0"
    assert list(indicator.inputs.keys()) == ["in_0", "in_1"]
    assert indicator.inputs["in_0"]["inline"] == "Fast_length"
    assert indicator.inputs["in_0"]["internalID"] == "Fast_length"
    assert indicator.inputs["in_0"]["value"] == 9
    assert indicator.inputs["in_1"]["inline"] == "mode"
    assert indicator.inputs["in_1"]["internalID"] == "modeId"
    assert indicator.inputs["in_1"]["isHidden"] is True
    assert indicator.inputs["in_1"]["options"] == ["A", "B"]
    assert indicator.plots == {
        "plot_0": "MA_line",
        "plot_1": "MA_line_2",
        "plot_2": "MA_line_3",
        "plot_3": "MA_line_colorer",
    }
