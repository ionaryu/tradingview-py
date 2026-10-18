from __future__ import annotations

from typing import Any

from .._types import AttrDict

MarketSymbol = str
Timeframe = str
Timezone = str
ChartType = str

CHART_TYPE_STUDIES: dict[str, str] = {
    "HeikinAshi": "BarSetHeikenAshi@tv-basicstudies-60!",
    "Renko": "BarSetRenko@tv-prostudies-40!",
    "LineBreak": "BarSetPriceBreak@tv-prostudies-34!",
    "Kagi": "BarSetKagi@tv-prostudies-34!",
    "PointAndFigure": "BarSetPnF@tv-prostudies-34!",
    "Range": "BarSetRange@tv-basicstudies-72!",
}

ChartTypeInputs = dict[str, Any]
Adjustment = str
TradingSession = str
Candle = AttrDict
Subsession = AttrDict
SymbolInfo = AttrDict
