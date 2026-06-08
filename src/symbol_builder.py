"""
Build create_schematic_symbol pin strings from parsed pin table + grouping rules.
Format per pin: "num|name|type|orient|x|y|owner"
"""

from __future__ import annotations

import re
from typing import Any

# Side placement in mils (symbol-local coordinates)
LEFT_X = 300
RIGHT_X = 1000
TOP_Y = 1000
BOTTOM_Y = 0
PIN_SPACING = 100


def _port_key(name: str) -> str:
    return name.upper().replace(".", "").replace("_", "")


def _classify_pin(pin: dict[str, Any]) -> str:
    name = pin["pin_name"]
    key = _port_key(name)
    alt = [_port_key(a) for a in pin.get("alt_functions") or []]
    all_names = {key, *alt}

    if key in ("GND", "VSS") or "GND" in all_names:
        return "power"
    if key in ("VDD", "VCC", "AVDD", "3V3") or "VDD" in all_names:
        return "power"
    if "NRST" in all_names or "RESET" in all_names:
        return "reset"
    if "ICECLK" in all_names or "ICEDAT" in all_names or "ICE" in key:
        return "debug"
    if key.startswith("PA") or any(a.startswith("PA") for a in alt):
        m = re.search(r"PA(\d+)", key) or next(
            (re.search(r"PA(\d+)", a) for a in alt if re.search(r"PA(\d+)", a)), None
        )
        if m:
            n = int(m.group(1))
            return "gpio_a" if n <= 11 else "gpio_b"
    if key.startswith("PB") or any(a.startswith("PB") for a in alt):
        return "gpio_b"
    if key == "NC" or pin.get("pin_type", "").lower() == "passive":
        return "nc"
    return "other"


def _orient_for_side(side: str) -> str:
    return {
        "left": "right",
        "right": "left",
        "top": "down",
        "bottom": "up",
    }.get(side, "right")


def _electrical(pin_type: str) -> str:
    t = pin_type.lower()
    if t in ("power",):
        return "power"
    if t in ("input",):
        return "input"
    if t in ("output",):
        return "output"
    if t in ("passive",):
        return "passive"
    return "io"


def build_symbol_pins(pins: list[dict[str, Any]], part_count: int = 1) -> list[str]:
    """
    Group pins: left=power+reset+debug, right=GPIO_A, top=GPIO_B, bottom=NC.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "left": [],
        "right": [],
        "top": [],
        "bottom": [],
    }

    for pin in pins:
        cat = _classify_pin(pin)
        if cat in ("power", "reset", "debug"):
            buckets["left"].append(pin)
        elif cat == "gpio_a":
            buckets["right"].append(pin)
        elif cat in ("gpio_b", "other"):
            buckets["top"].append(pin)
        elif cat == "nc":
            buckets["bottom"].append(pin)
        else:
            buckets["right"].append(pin)

    def sort_gpio(ps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def key(p: dict[str, Any]) -> tuple[int, str]:
            m = re.search(r"(\d+)", p["pin_name"])
            return (int(m.group(1)) if m else 99, p["pin_name"])

        return sorted(ps, key=key)

    for side in ("right", "top", "left", "bottom"):
        if side in ("right", "top"):
            buckets[side] = sort_gpio(buckets[side])
        else:
            buckets[side] = sorted(buckets[side], key=lambda p: int(p["pin_num"]))

    lines: list[str] = []
    side_coords = {
        "left": (LEFT_X, None),
        "right": (RIGHT_X, None),
        "top": (None, TOP_Y),
        "bottom": (None, BOTTOM_Y),
    }

    for side, plist in buckets.items():
        for i, pin in enumerate(plist):
            if side in ("left", "right"):
                x = side_coords[side][0]
                y = i * PIN_SPACING
            else:
                x = i * PIN_SPACING + 400
                y = side_coords[side][1]
            orient = _orient_for_side(side)
            line = (
                f"{pin['pin_num']}|{pin['pin_name']}|{_electrical(pin['pin_type'])}|"
                f"{orient}|{x}|{y}|1"
            )
            lines.append(line)

    return lines


def build_create_schematic_symbol_payload(
    symbol_name: str,
    pins: list[dict[str, Any]],
    description: str | None = None,
) -> dict[str, Any]:
    pin_lines = build_symbol_pins(pins)
    if description:
        pin_lines.insert(0, f"Description={description}")
    return {
        "symbol_name": symbol_name,
        "description": description or symbol_name,
        "pins": pin_lines,
        "part_count": 1,
    }
