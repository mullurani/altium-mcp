"""
Generate place_net_labels / place_power_ports assignments and component placement list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _norm(s: str) -> str:
    return s.upper().replace(".", "").replace("_", "")


def _find_pin_by_alt(pins: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = _norm(name)
    for p in pins:
        if _norm(p["pin_name"]) == target:
            return p
        for a in p.get("alt_functions") or []:
            if _norm(a) == target:
                return p
    return None


def _find_pin_by_port(pins: list[dict[str, Any]], port: str) -> dict[str, Any] | None:
    port_n = _norm(port)
    for p in pins:
        if _norm(p["pin_name"]) == port_n:
            return p
        for a in p.get("alt_functions") or []:
            if _norm(a) == port_n:
                return p
    return None


def resolve_mcu_pin_count(design: dict[str, Any]) -> int:
    pkg = design.get("mcu_package", "").upper()
    if "32" in pkg or "LQFP" in pkg:
        return 32
    return 20


def build_net_label_assignments(
    design: dict[str, Any], mcu_pins: list[dict[str, Any]]
) -> list[str]:
    assignments: list[str] = []
    mcu = design["mcu"]

    for inp in design.get("inputs", []):
        port = inp["port"]
        net = inp["id"]
        assignments.append(f"U1|{port}|{net}")

    for out in design.get("outputs", []):
        port = out["port"]
        net = out["drive_net"]
        assignments.append(f"U1|{port}|{net}")

    debug_pins = design.get("connectors", {}).get("debug_pins", [])
    net_debug = design.get("net_names", {}).get("debug", [])
    if set(debug_pins) != set(net_debug):
        raise ValueError("connectors.debug_pins must match net_names.debug")

    header_map = {"ICE_CLK": "1", "ICE_DAT": "2"}
    for dbg in debug_pins:
        pin = _find_pin_by_alt(mcu_pins, dbg)
        if pin is None:
            raise ValueError(
                f"Cannot find {dbg} in parsed pin table for {mcu}. "
                f"Check design/pinmaps/{mcu}.json alt_functions."
            )
        label_pin = pin["pin_name"]
        if _norm(label_pin) not in (_norm(dbg), _norm(dbg.replace("_", ""))):
            if _norm(dbg) in (_norm(label_pin),):
                label_pin = dbg
        assignments.append(f"U1|{label_pin}|{dbg}")
        assignments.append(f"J_DBG|{header_map.get(dbg, '1')}|{dbg}")

    return assignments


def build_power_port_assignments(design: dict[str, Any]) -> list[str]:
    power = design.get("power", {})
    rails = [
        (power.get("output", "3V3"), "VCC"),
        (power.get("output_gnd", "GND"), "GND"),
        (power.get("input", "24V"), "VCC"),
        (power.get("input_gnd", "24V_GND"), "GND"),
    ]
    assignments: list[str] = []
    for net, style in rails:
        assignments.append(f"{net}|{style}|0|0")
    assignments.append("J_DBG|3|GND|0|0")
    assignments.append("J_DBG|4|3V3|0|0")
    return assignments


def build_passive_components(design: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    r_idx = 1
    for inp in design.get("inputs", []):
        parts.append(
            {
                "designator": f"R{r_idx}",
                "symbol": "RES",
                "lib_ref": "RES",
                "value": f"{inp['pullup_ohms']}",
                "footprint": design["footprints"].get("RES", "RES0603"),
            }
        )
        r_idx += 1
        parts.append(
            {
                "designator": f"U{10 + len(parts)}",
                "symbol": inp["opto"],
                "lib_ref": inp["opto"],
                "footprint": design["footprints"][inp["opto"]],
            }
        )
    for out in design.get("outputs", []):
        parts.append(
            {
                "designator": f"R{r_idx}",
                "symbol": "RES",
                "lib_ref": "RES",
                "value": f"{out['base_ohms']}",
                "footprint": design["footprints"].get("RES", "RES0603"),
            }
        )
        r_idx += 1
        parts.append(
            {
                "designator": f"Q{len([p for p in parts if p['designator'].startswith('Q')]) + 1}",
                "symbol": out["driver"],
                "lib_ref": out["driver"],
                "footprint": design["footprints"][out["driver"]],
            }
        )
    return parts


def build_component_placement_list(
    design: dict[str, Any], mcu_pins: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """All components to place with layout coordinates in mils."""
    project_path = design["project_path"].replace("\\", "/")
    sym_lib = design["library_paths"]["symbol_lib"].replace("{project_path}", project_path)

    def comp(des: str, sym: str, x: int, y: int) -> dict[str, Any]:
        return {
            "designator": des,
            "symbol_name": sym,
            "library_path": sym_lib,
            "x": x,
            "y": y,
        }

    components: list[dict[str, Any]] = [
        comp("U1", design["mcu"], 3000, 2000),
        comp("U2", design["power"]["module"], 4500, 4000),
        comp("J_IN1", design["connectors"]["inputs"], 100, 1500),
        comp("J_IN2", design["connectors"]["inputs"], 100, 2500),
        comp("J_OUT1", design["connectors"]["outputs"], 5900, 1500),
        comp("J_OUT2", design["connectors"]["outputs"], 5900, 2500),
        comp("J_DBG", design["connectors"]["debug"], 3000, 500),
    ]

    y = 1000
    for i, inp in enumerate(design.get("inputs", []), start=1):
        components.append(comp(f"U{2 + i}", inp["opto"], 1500, y))
        components.append(comp(f"R{i}", "RES", 2000, y))
        y += 500

    y = 1000
    for i, out in enumerate(design.get("outputs", []), start=1):
        components.append(comp(f"Q{i}", out["driver"], 4000, y))
        components.append(comp(f"R{10 + i}", "RES", 3500, y))
        components.append(comp(f"K{i}", "RELAY", 5000, y))
        y += 500

    return components


def expected_designators(design: dict[str, Any]) -> list[str]:
    return sorted(c["designator"] for c in build_component_placement_list(design, []))


def all_net_names_flat(design: dict[str, Any]) -> list[str]:
    nets: list[str] = []
    for group in design.get("net_names", {}).values():
        nets.extend(group)
    return nets


def validate_design(design: dict[str, Any]) -> None:
    required = [
        "project_name",
        "project_path",
        "mcu",
        "mcu_package",
        "power",
        "inputs",
        "outputs",
        "connectors",
        "net_names",
        "library_paths",
        "footprints",
    ]
    for key in required:
        if key not in design:
            raise ValueError(f"design.json missing required key: {key}")
    dbg_c = design["connectors"].get("debug_pins", [])
    dbg_n = design["net_names"].get("debug", [])
    if set(dbg_c) != set(dbg_n):
        raise ValueError("connectors.debug_pins must match net_names.debug")


def load_design(path: Path) -> dict[str, Any]:
    design = json.loads(path.read_text(encoding="utf-8"))
    validate_design(design)
    return design
