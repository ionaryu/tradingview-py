from tradingview.indicators.pine_indicator import PineIndicator


def make_pine() -> PineIndicator:
    """Small Pine indicator definition used across tests."""
    return PineIndicator(
        {
            "id": "PUB;test",
            "version": "3.0",
            "description": "Test indicator",
            "shortDescription": "TEST",
            "script": "bmI9Ii...IL",
            "inputs": {
                "in_0": {
                    "name": "Length",
                    "inline": "Length",
                    "internalID": "length",
                    "type": "integer",
                    "value": 14,
                    "isHidden": False,
                    "isFake": False,
                },
                "in_1": {
                    "name": "Source",
                    "inline": "Source",
                    "internalID": "src",
                    "type": "source",
                    "value": "close",
                    "isHidden": False,
                    "isFake": False,
                    "options": ["close", "open"],
                },
                "in_2": {
                    "name": "Color",
                    "inline": "Color",
                    "internalID": "color",
                    "type": "color",
                    "value": "#ff0000",
                    "isHidden": False,
                    "isFake": True,
                },
                "in_3": {
                    "name": "Show",
                    "inline": "Show",
                    "type": "bool",
                    "value": True,
                    "isHidden": False,
                    "isFake": False,
                },
            },
            "plots": {"plot_0": "Value", "plot_1": "Value", "plot_2": "Signal"},
        }
    )


makePine = make_pine
