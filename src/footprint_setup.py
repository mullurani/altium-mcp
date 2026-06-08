"""
Generate standard footprints via create_pcb_footprint MCP command.
"""

from __future__ import annotations

from typing import Any, Callable

# Pad format: pad_number|x_mm|y_mm|width_mm|height_mm|shape

def _tssop_pads(count: int, pitch: float, span: float) -> list[str]:
    pads = []
    y = span / 2
    for i in range(count // 2):
        x = -((count // 4) * pitch) + i * pitch
        pads.append(f"{i + 1}|{x:.3f}|{y:.3f}|0.40|1.50|Rect")
    for i in range(count // 2):
        x = -((count // 4) * pitch) + i * pitch
        pads.append(f"{count - i}|{x:.3f}|{-y:.3f}|0.40|1.50|Rect")
    return pads


def _dual_row(count: int, pitch: float, row_spacing: float) -> list[str]:
    pads = []
    half = count // 2
    for i in range(half):
        x = (i - half / 2 + 0.5) * pitch
        pads.append(f"{i + 1}|{x:.3f}|{row_spacing / 2:.3f}|0.60|1.20|Rect")
    for i in range(half):
        x = (i - half / 2 + 0.5) * pitch
        pads.append(f"{count - i}|{x:.3f}|{-row_spacing / 2:.3f}|0.60|1.20|Rect")
    return pads


FOOTPRINT_SPECS = {
    "TSSOP20": {"description": "TSSOP20 0.65mm", "pads": _tssop_pads(20, 0.65, 6.5)},
    "LQFP32": {"description": "LQFP32 0.8mm", "pads": _tssop_pads(32, 0.8, 9.0)},
    "SIP7": {
        "description": "SIP7 2.54mm // TODO: through-hole",
        "pads": [f"{i + 1}|0|{(i - 3) * 2.54:.2f}|1.2|1.2|Round" for i in range(7)],
    },
    "SOP4": {
        "description": "SOP4 1.27mm",
        "pads": ["1|-1.905|2.3|1.0|1.4|Rect", "2|-1.905|-2.3|1.0|1.4|Rect",
                 "3|1.905|-2.3|1.0|1.4|Rect", "4|1.905|2.3|1.0|1.4|Rect"],
    },
    "SOT23": {
        "description": "SOT23",
        "pads": ["1|-0.95|1.0|0.60|0.70|Rect", "2|0.95|1.0|0.60|0.70|Rect", "3|0|-1.15|0.60|0.70|Rect"],
    },
    "KF301-2P": {
        "description": "KF301 2P terminal",
        "pads": ["1|-1.27|0|1.4|1.4|Round", "2|1.27|0|1.4|1.4|Round"],
    },
    "KF301-3P": {
        "description": "KF301 3P terminal",
        "pads": [f"{i + 1}|{(i - 1) * 2.54:.2f}|0|1.4|1.4|Round" for i in range(3)],
    },
    "HDR2x2": {
        "description": "2x2 header 2.54mm",
        "pads": [
            "1|-1.27|1.27|1.0|1.0|Round",
            "2|1.27|1.27|1.0|1.0|Round",
            "3|-1.27|-1.27|1.0|1.0|Round",
            "4|1.27|-1.27|1.0|1.0|Round",
        ],
    },
}

EXPECTED_PAD_COUNTS = {
    "TSSOP20": 20,
    "LQFP32": 32,
    "SIP7": 7,
    "SOP4": 4,
    "SOT23": 3,
    "KF301-2P": 2,
    "KF301-3P": 3,
    "HDR2x2": 4,
}


def create_all_footprints(execute_fn: Callable[[str, dict], dict], *, verbose: bool = True) -> list[str]:
    """Idempotent: creates each footprint in the active PcbLib."""
    created = []
    for name, spec in FOOTPRINT_SPECS.items():
        if verbose:
            print(f"  footprint: {name}")
        execute_fn(
            "create_pcb_footprint",
            {
                "footprint_name": name,
                "description": spec["description"],
                "pads": spec["pads"],
            },
        )
        created.append(name)
    return created
