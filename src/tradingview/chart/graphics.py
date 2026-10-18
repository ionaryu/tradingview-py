from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .._types import AttrDict

RawGraphics = dict[str, dict[str, Any]]
ExtendValue = str
YLocValue = str
LabelStyleValue = str
LineStyleValue = str
BoxStyleValue = str
SizeValue = str
VAlignValue = str
HAlignValue = str
TextWrapValue = str
TablePositionValue = str

GraphicLabel = AttrDict
GraphicLine = AttrDict
GraphicBox = AttrDict
TableCell = AttrDict
GraphicTable = AttrDict
GraphicHorizLine = AttrDict
GraphicPoint = AttrDict
GraphicPolygon = AttrDict
GraphicHorizHist = AttrDict
GraphicsData = AttrDict

_TRANSLATOR = {
    "extend": {"r": "right", "l": "left", "b": "both", "n": "none"},
    "yLoc": {"pr": "price", "ab": "abovebar", "bl": "belowbar"},
    "labelStyle": {
        "n": "none",
        "xcr": "xcross",
        "cr": "cross",
        "tup": "triangleup",
        "tdn": "triangledown",
        "flg": "flag",
        "cir": "circle",
        "aup": "arrowup",
        "adn": "arrowdown",
        "lup": "label_up",
        "ldn": "label_down",
        "llf": "label_left",
        "lrg": "label_right",
        "llwlf": "label_lower_left",
        "llwrg": "label_lower_right",
        "luplf": "label_upper_left",
        "luprg": "label_upper_right",
        "lcn": "label_center",
        "sq": "square",
        "dia": "diamond",
    },
    "lineStyle": {
        "sol": "solid",
        "dot": "dotted",
        "dsh": "dashed",
        "al": "arrow_left",
        "ar": "arrow_right",
        "ab": "arrow_both",
    },
    "boxStyle": {"sol": "solid", "dot": "dotted", "dsh": "dashed"},
}


def parse_graphics(
    raw: dict[str, dict[str, Any]] | None = None,
    indexes: Sequence[int | None] = (),
) -> GraphicsData:
    """Converts raw indicator graphics into readable objects."""
    raw_data = raw if raw is not None else {}

    def values(g_type: str) -> list[dict[str, Any]]:
        group = raw_data.get(g_type) or {}
        return list(group.values())

    def x(idx: Any) -> int | None:
        if isinstance(idx, int) and 0 <= idx < len(indexes):
            return indexes[idx]
        return None

    tables: list[AttrDict] = []
    for t in values("dwgtables"):
        cells_by_row: dict[int, dict[int, AttrDict]] = {}
        max_row = -1
        for cell in values("dwgtablecells"):
            if cell.get("tid") != t.get("id"):
                continue
            r = int(cell.get("row", 0))
            c = int(cell.get("col", 0))
            max_row = max(max_row, r)
            row_dict = cells_by_row.setdefault(r, {})
            row_dict[c] = AttrDict(
                {
                    "id": cell.get("id"),
                    "text": cell.get("t"),
                    "width": cell.get("w"),
                    "height": cell.get("h"),
                    "textColor": cell.get("tc"),
                    "textHAlign": cell.get("tha"),
                    "textVAlign": cell.get("tva"),
                    "textSize": cell.get("ts"),
                    "bgColor": cell.get("bgc"),
                }
            )
        cells: list[list[Any]] = []
        for r in range(max_row + 1):
            row_dict = cells_by_row.get(r, {})
            if not row_dict:
                cells.append([])
            else:
                max_col = max(row_dict.keys())
                cells.append([row_dict.get(c) for c in range(max_col + 1)])
        tables.append(
            AttrDict(
                {
                    "id": t.get("id"),
                    "position": t.get("pos"),
                    "rows": t.get("rows"),
                    "columns": t.get("cols"),
                    "bgColor": t.get("bgc"),
                    "frameColor": t.get("frmc"),
                    "frameWidth": t.get("frmw"),
                    "borderColor": t.get("brdc"),
                    "borderWidth": t.get("brdw"),
                    "cells": cells,
                }
            )
        )

    return AttrDict(
        {
            "labels": [
                AttrDict(
                    {
                        "id": l.get("id"),
                        "x": x(l.get("x")),
                        "y": l.get("y"),
                        "yLoc": _TRANSLATOR["yLoc"].get(l.get("yl"), l.get("yl")),
                        "text": l.get("t"),
                        "style": _TRANSLATOR["labelStyle"].get(l.get("st"), l.get("st")),
                        "color": l.get("ci"),
                        "textColor": l.get("tci"),
                        "size": l.get("sz"),
                        "textAlign": l.get("ta"),
                        "toolTip": l.get("tt"),
                    }
                )
                for l in values("dwglabels")
            ],
            "lines": [
                AttrDict(
                    {
                        "id": l.get("id"),
                        "x1": x(l.get("x1")),
                        "y1": l.get("y1"),
                        "x2": x(l.get("x2")),
                        "y2": l.get("y2"),
                        "extend": _TRANSLATOR["extend"].get(l.get("ex"), l.get("ex")),
                        "style": _TRANSLATOR["lineStyle"].get(l.get("st"), l.get("st")),
                        "color": l.get("ci"),
                        "width": l.get("w"),
                    }
                )
                for l in values("dwglines")
            ],
            "boxes": [
                AttrDict(
                    {
                        "id": b.get("id"),
                        "x1": x(b.get("x1")),
                        "y1": b.get("y1"),
                        "x2": x(b.get("x2")),
                        "y2": b.get("y2"),
                        "color": b.get("c"),
                        "bgColor": b.get("bc"),
                        "extend": _TRANSLATOR["extend"].get(b.get("ex"), b.get("ex")),
                        "style": _TRANSLATOR["boxStyle"].get(b.get("st"), b.get("st")),
                        "width": b.get("w"),
                        "text": b.get("t"),
                        "textSize": b.get("ts"),
                        "textColor": b.get("tc"),
                        "textVAlign": b.get("tva"),
                        "textHAlign": b.get("tha"),
                        "textWrap": b.get("tw"),
                    }
                )
                for b in values("dwgboxes")
            ],
            "tables": tables,
            "horizLines": [
                AttrDict(
                    {
                        **h,
                        "startIndex": x(h.get("startIndex")),
                        "endIndex": x(h.get("endIndex")),
                    }
                )
                for h in values("horizlines")
            ],
            "polygons": [
                AttrDict(
                    {
                        **p,
                        "points": [
                            AttrDict({**pt, "index": x(pt.get("index"))}) for pt in (p.get("points") or [])
                        ],
                    }
                )
                for p in values("polygons")
            ],
            "horizHists": [
                AttrDict(
                    {
                        **h,
                        "firstBarTime": x(h.get("firstBarTime")),
                        "lastBarTime": x(h.get("lastBarTime")),
                    }
                )
                for h in values("hhists")
            ],
            "raw": raw_data,
        }
    )


parseGraphics = parse_graphics


def apply_graphics_commands(graphics: dict[str, dict[str, Any]], commands: dict[str, Any] | None) -> None:
    """Applies `graphicsCmds` (erase then create) to raw graphics in place."""
    if not commands:
        return
    for instruction in commands.get("erase") or ():
        action = instruction.get("action")
        g_type = instruction.get("type")
        if action == "all":
            if not g_type:
                for k in list(graphics.keys()):
                    graphics[k] = {}
            else:
                graphics.pop(g_type, None)
        elif action == "one" and g_type:
            bucket = graphics.get(g_type)
            if isinstance(bucket, dict):
                item_id = instruction.get("id")
                bucket.pop(item_id, None)
                bucket.pop(str(item_id), None)

    for g_type, groups in (commands.get("create") or {}).items():
        bucket = graphics.setdefault(g_type, {})
        for group in groups or ():
            for item in group.get("data") or ():
                bucket[str(item["id"])] = item


applyGraphicsCommands = apply_graphics_commands
