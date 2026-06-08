from src.datasheet_parser import load_curated
from src.symbol_builder import build_create_schematic_symbol_payload, build_symbol_pins

def test_symbol_pin_format_fb0ae():
    pins = load_curated("M031FB0AE")
    lines = build_symbol_pins(pins)
    assert len(lines) == 20
    for line in lines:
        parts = line.split("|")
        assert len(parts) >= 6


def test_symbol_pin_format_eb0ae():
    pins = load_curated("M031EB0AE")
    lines = build_symbol_pins(pins)
    assert len(lines) == 32


def test_mcu_payload():
    pins = load_curated("M031FB0AE")
    payload = build_create_schematic_symbol_payload("M031FB0AE", pins)
    assert payload["symbol_name"] == "M031FB0AE"
    assert len(payload["pins"]) >= 20
