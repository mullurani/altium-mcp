from pathlib import Path

from src.datasheet_parser import load_curated, parse

ROOT = Path(__file__).resolve().parent.parent


def test_curated_m031fb0ae():
    pins = load_curated("M031FB0AE")
    assert pins is not None
    assert len(pins) == 20
    names = {p["pin_name"] for p in pins}
    assert "PA0" in names
    assert "ICE_CLK" in names
    assert "ICE_DAT" in names


def test_curated_m031eb0ae():
    pins = load_curated("M031EB0AE")
    assert pins is not None
    assert len(pins) == 32


def test_parse_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("src.datasheet_parser.CACHE_DIR", tmp_path / "cache")
    pins = parse("M031FB0AE", "TSSOP20", use_cache=True)
    assert len(pins) == 20
    assert (tmp_path / "cache" / "M031FB0AE_pins.json").exists()
