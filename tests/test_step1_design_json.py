import json
from pathlib import Path

import pytest

from src.netlist_builder import load_design, validate_design

ROOT = Path(__file__).resolve().parent.parent


def test_design_json_loads():
    design = load_design(ROOT / "design" / "design.json")
    assert design["mcu"] == "M031FB0AE"
    assert design["connectors"]["debug_pins"] == design["net_names"]["debug"]


def test_required_keys():
    design = json.loads((ROOT / "design" / "design.json").read_text(encoding="utf-8"))
    validate_design(design)


def test_debug_pins_match():
    design = load_design(ROOT / "design" / "design.json")
    with pytest.raises(ValueError):
        bad = dict(design)
        bad["net_names"] = dict(design["net_names"])
        bad["net_names"]["debug"] = ["X"]
        validate_design(bad)
