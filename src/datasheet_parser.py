"""
Parse MCU pin tables from PDF (pdfplumber), cache, or curated design/pinmaps/*.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"
PINMAPS_DIR = REPO_ROOT / "design" / "pinmaps"
DATASHEET_URL = (
    "https://www.nuvoton.com/export/resource-files/"
    "DS_M031_M032_Series_EN_Rev2.02.pdf"
)
DATASHEET_FILENAME = "DS_M031_M032_Series_EN_Rev2.02.pdf"


def _normalize_pin_entry(raw: dict[str, Any]) -> dict[str, Any]:
    alt = raw.get("alt_functions") or []
    if isinstance(alt, str):
        alt = [alt]
    return {
        "pin_num": str(raw.get("pin_num", "")).strip(),
        "pin_name": str(raw.get("pin_name", "")).strip(),
        "pin_type": str(raw.get("pin_type", "I/O")).strip(),
        "alt_functions": [str(a).strip() for a in alt if str(a).strip()],
    }


def load_curated(part_number: str) -> list[dict[str, Any]] | None:
    path = PINMAPS_DIR / f"{part_number}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    pins = data.get("pins") or []
    return [_normalize_pin_entry(p) for p in pins]


def _diff_pins(
    parsed: list[dict[str, Any]], curated: list[dict[str, Any]]
) -> list[str]:
    warnings: list[str] = []
    curated_by_num = {p["pin_num"]: p for p in curated}
    for p in parsed:
        c = curated_by_num.get(p["pin_num"])
        if not c:
            warnings.append(f"pin {p['pin_num']}: missing in curated map")
            continue
        if p["pin_name"].upper() != c["pin_name"].upper():
            warnings.append(
                f"pin {p['pin_num']}: name {p['pin_name']} != curated {c['pin_name']}"
            )
    return warnings


def _parse_pdf_pins(part_number: str, package: str, pdf_path: Path) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber not installed; pip install -r requirements-build.txt") from exc

    pins: list[dict[str, Any]] = []
    pkg_upper = package.upper()
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if part_number not in text and pkg_upper not in text:
                continue
            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    num = str(row[0] or "").strip()
                    if not re.match(r"^\d{1,2}$", num):
                        continue
                    name = str(row[1] or "").strip()
                    if not name or name.lower() in ("pin", "name", "symbol"):
                        continue
                    pin_type = "I/O"
                    if name.upper() in ("GND", "VSS"):
                        pin_type = "Power"
                    elif name.upper() in ("VDD", "VCC", "AVDD"):
                        pin_type = "Power"
                    alt: list[str] = []
                    if len(row) > 2 and row[2]:
                        alt = [s.strip() for s in re.split(r"[,/\s]+", str(row[2])) if s.strip()]
                    pins.append(
                        _normalize_pin_entry(
                            {
                                "pin_num": num,
                                "pin_name": name.replace(".", ""),
                                "pin_type": pin_type,
                                "alt_functions": alt,
                            }
                        )
                    )
    return pins


def _download_datasheet(dest: Path) -> Path:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    print(f"Downloading datasheet to {dest}...")
    resp = requests.get(DATASHEET_URL, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def print_pin_table(pins: list[dict[str, Any]], part_number: str) -> None:
    print(f"\n=== Pin table: {part_number} ({len(pins)} pins) ===")
    print(f"{'#':<4} {'Name':<12} {'Type':<8} Alt functions")
    print("-" * 60)
    for p in pins:
        alt = ", ".join(p.get("alt_functions") or [])
        print(f"{p['pin_num']:<4} {p['pin_name']:<12} {p['pin_type']:<8} {alt}")
    print()


def parse(
    part_number: str,
    package: str | None = None,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Return pin list for part_number. Curated pinmap wins on mismatch (with warning).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{part_number}_pins.json"

    if use_cache and cache_path.exists() and not force_refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        print_pin_table(cached, part_number)
        return cached

    curated = load_curated(part_number)
    if curated is None:
        raise FileNotFoundError(
            f"No curated pinmap at design/pinmaps/{part_number}.json"
        )

    parsed_from_pdf: list[dict[str, Any]] = []
    try:
        pdf_path = _download_datasheet(CACHE_DIR / DATASHEET_FILENAME)
        if package:
            parsed_from_pdf = _parse_pdf_pins(part_number, package, pdf_path)
    except Exception as exc:
        print(f"PDF parse skipped ({exc}); using curated pinmap.", file=sys.stderr)

    if parsed_from_pdf and len(parsed_from_pdf) >= len(curated) // 2:
        warnings = _diff_pins(parsed_from_pdf, curated)
        for w in warnings:
            print(f"WARNING: parser vs curated: {w}", file=sys.stderr)
        if warnings:
            print("Using curated pinmap as authoritative.", file=sys.stderr)
            pins = curated
        else:
            pins = parsed_from_pdf
    else:
        pins = curated

    cache_path.write_text(json.dumps(pins, indent=2), encoding="utf-8")
    print_pin_table(pins, part_number)
    return pins


if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "M031FB0AE"
    pkg = sys.argv[2] if len(sys.argv) > 2 else "TSSOP20"
    parse(part, pkg)
