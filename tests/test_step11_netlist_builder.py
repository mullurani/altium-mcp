from pathlib import Path

from src.datasheet_parser import load_curated
from src.netlist_builder import (
    all_net_names_flat,
    build_net_label_assignments,
    build_power_port_assignments,
    expected_designators,
    load_design,
)

ROOT = Path(__file__).resolve().parent.parent


def test_net_assignments_complete():
    design = load_design(ROOT / "design" / "design.json")
    pins = load_curated(design["mcu"])
    labels = build_net_label_assignments(design, pins)
    assert "U1|PA0|IN1" in labels
    assert "U1|PA3|RELAY2_DRV" in labels
    assert any("ICE_CLK" in a for a in labels)
    assert any("J_DBG" in a for a in labels)


def test_power_ports():
    design = load_design(ROOT / "design" / "design.json")
    power = build_power_port_assignments(design)
    assert len(power) >= 4


def test_expected_designators_unique():
    design = load_design(ROOT / "design" / "design.json")
    des = expected_designators(design)
    assert len(des) == len(set(des))
    assert "U1" in des


def test_all_nets_flat():
    design = load_design(ROOT / "design" / "design.json")
    nets = all_net_names_flat(design)
    assert "IN1" in nets
    assert "ICE_DAT" in nets
