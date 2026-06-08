#!/usr/bin/env python3
"""
Altium automated project builder — orchestrates MCP bridge commands from design.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from src.altium_client import AltiumClient
from src.datasheet_parser import parse as parse_pins
from src.footprint_setup import EXPECTED_PAD_COUNTS, create_all_footprints
from src.netlist_builder import (
    all_net_names_flat,
    build_component_placement_list,
    build_net_label_assignments,
    build_power_port_assignments,
    expected_designators,
    load_design,
    resolve_mcu_pin_count,
    validate_design,
)
from src.symbol_builder import build_create_schematic_symbol_payload
from src.visual_checker import (
    build_corrections,
    evaluate_visual_rules,
    get_visual_rules,
    reset_rule4_state,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build")

EXIT_SUCCESS = 0
EXIT_STRUCTURAL = 1
EXIT_VISUAL_WARN = 2

exit_code = EXIT_SUCCESS


@dataclass
class CheckResult:
    passed: bool
    message: str = ""


class StepVerificationError(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message


# Simple symbol pin templates (mils) for non-MCU parts
SIMPLE_SYMBOLS: dict[str, list[str]] = {
    "RES": ["1|1|passive|right|300|500|1", "2|2|passive|left|700|500|1", "Description=Resistor"],
    "PC817": [
        "1|A|passive|left|300|400|1",
        "2|C|passive|right|700|400|1",
        "3|E|passive|left|300|600|1",
        "4|D|passive|right|700|600|1",
        "Description=Optocoupler PC817",
    ],
    "BC547": [
        "1|B|input|left|300|500|1",
        "2|E|passive|down|500|300|1",
        "3|C|output|right|700|500|1",
        "Description=NPN BC547",
    ],
    "B2403S-1WR3": [
        "1|VIN|power|left|300|600|1",
        "2|GND|power|left|300|400|1",
        "3|+VO|power|right|700|600|1",
        "4|-VO|power|right|700|400|1",
        "Description=Isolated DC-DC",
    ],
    "KF301-2P": ["1|1|passive|down|400|700|1", "2|2|passive|down|600|700|1", "Description=Terminal 2P"],
    "KF301-3P": [
        "1|1|passive|down|300|700|1",
        "2|2|passive|down|500|700|1",
        "3|3|passive|down|700|700|1",
        "Description=Terminal 3P",
    ],
    "HDR2x2": [
        "1|1|passive|down|400|700|1",
        "2|2|passive|down|600|700|1",
        "3|3|passive|down|400|500|1",
        "4|4|passive|down|600|500|1",
        "Description=Debug header",
    ],
    "RELAY": [
        "1|COIL+|passive|left|300|500|1",
        "2|COIL-|passive|left|300|300|1",
        "3|COM|passive|right|700|500|1",
        "4|NO|passive|right|700|300|1",
        "Description=Relay",
    ],
}


def set_exit_code(code: int) -> None:
    global exit_code
    if code > exit_code:
        exit_code = code


def expand_paths(design: dict) -> dict:
    pp = design["project_path"].replace("\\", "/")
    for key, val in design.get("library_paths", {}).items():
        if isinstance(val, str):
            design["library_paths"][key] = val.replace("{project_path}", pp)
    return design


def checkpoint_path(design: dict) -> Path:
    return Path(design["project_path"]) / ".build_state.json"


def load_checkpoint(design: dict) -> dict:
    cp = checkpoint_path(design)
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    return {"completed_steps": []}


def save_checkpoint(design: dict, state: dict) -> None:
    cp = checkpoint_path(design)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(state, indent=2), encoding="utf-8")


def step_done(state: dict, name: str) -> bool:
    return name in state.get("completed_steps", [])


def mark_step(state: dict, name: str) -> None:
    steps = state.setdefault("completed_steps", [])
    if name not in steps:
        steps.append(name)


def run_pytest_preflight() -> None:
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.exists():
        return
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests_dir), "-q"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        logger.error(proc.stdout + proc.stderr)
        raise StepVerificationError("pytest", "pre-flight tests failed")


def write_test_log_entry(step: str, structural_ok: bool, violations: list) -> None:
    log_path = REPO_ROOT / "tests" / "test_log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status = "pass" if structural_ok and not violations else ("warn" if structural_ok else "fail")
    line = f"- **{step}**: {status} ({len(violations)} visual violations)\n"
    if not log_path.exists():
        log_path.write_text("# Build test log\n\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def save_screenshot(step: str, attempt: int, data: dict) -> None:
    out_dir = REPO_ROOT / "tests" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    b64 = data.get("image_base64") or ""
    if isinstance(data.get("result"), str):
        try:
            parsed = json.loads(data["result"])
            b64 = parsed.get("image_base64", b64)
        except json.JSONDecodeError:
            pass
    if b64:
        (out_dir / f"{step}_attempt{attempt}.png").write_bytes(base64.b64decode(b64))


def verify_step(
    client: AltiumClient,
    step_name: str,
    structural_checks: list,
    visual_rule_names: list[str] | None = None,
    *,
    enable_visual: bool = True,
    max_visual_retries: int = 3,
) -> None:
    for check in structural_checks:
        result = check()
        if not result.passed:
            raise StepVerificationError(step_name, result.message)

    violations = []
    rules = get_visual_rules()
    rule_by_name = {r.name: r for r in rules}
    selected = [rule_by_name[n] for n in (visual_rule_names or []) if n in rule_by_name]

    if selected and enable_visual and os.environ.get("ANTHROPIC_API_KEY"):
        for attempt in range(max_visual_retries):
            try:
                shot = client.execute("get_screenshot", {"view_type": "sch"})
                save_screenshot(step_name, attempt, shot.get("result", shot))
                violations = evaluate_visual_rules(selected, shot.get("result", shot))
                if not violations:
                    logger.info("  visual ok  %s", step_name)
                    break
                corrections = build_corrections(violations, selected)
                for corr in corrections:
                    client.execute(corr.command, corr.params)
            except Exception as exc:
                logger.warning("Visual check skipped: %s", exc)
                break
        else:
            logger.warning(
                "  visual WARNING: %s has %s unfixed issues — see tests/screenshots/",
                step_name,
                len(violations),
            )
            set_exit_code(EXIT_VISUAL_WARN)
    elif selected and enable_visual:
        logger.warning("ANTHROPIC_API_KEY not set — skipping visual rules")

    write_test_log_entry(step_name, True, violations)


def create_symbols(client: AltiumClient, design: dict, mcu_pins: list) -> None:
    sym_lib = design["library_paths"]["symbol_lib"]
    symbols = set(SIMPLE_SYMBOLS.keys())
    symbols.add(design["mcu"])
    symbols.add(design["power"]["module"])
    for v in design["connectors"].values():
        if isinstance(v, str):
            symbols.add(v)

    mcu_payload = build_create_schematic_symbol_payload(design["mcu"], mcu_pins, design["mcu"])
    client.execute(
        "create_schematic_symbol",
        {
            "symbol_name": mcu_payload["symbol_name"],
            "description": mcu_payload["description"],
            "pins": mcu_payload["pins"],
            "part_count": mcu_payload["part_count"],
        },
    )

    for sym_name, pins in SIMPLE_SYMBOLS.items():
        if sym_name in (design["mcu"],):
            continue
        search = client.execute_safe(
            "search_library_symbol",
            {"library_path": sym_lib, "symbol_name": sym_name},
        )
        if search.get("success") and isinstance(search.get("result"), dict):
            if search["result"].get("found"):
                logger.info("Symbol %s already in lib, skipping", sym_name)
                continue
        client.execute(
            "create_schematic_symbol",
            {
                "symbol_name": sym_name,
                "description": sym_name,
                "pins": pins,
                "part_count": 1,
            },
        )


def main() -> int:
    global exit_code
    parser = argparse.ArgumentParser(description="Altium automated project builder")
    parser.add_argument("--config", default="design/design.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    design = expand_paths(load_design(REPO_ROOT / args.config))
    validate_design(design)

    if not args.dry_run:
        run_pytest_preflight()
    else:
        logger.info("Dry-run: skipping pytest pre-flight (use live run for full gate)")

    from bridge_client import altium_bridge  # noqa: E402

    client = AltiumClient(altium_bridge, dry_run=args.dry_run, verbose=args.verbose)
    state = load_checkpoint(design)
    project_path = Path(design["project_path"])
    project_file = project_path / f"{design['project_name']}.PrjPcb"
    sym_lib = design["library_paths"]["symbol_lib"]
    fp_lib = design["library_paths"]["footprint_lib"]
    sheet_path = project_path / "Schematic.SchDoc"
    pcb_path = project_path / "PCB.PcbDoc"

    if project_file.exists() and not checkpoint_path(design).exists() and not args.overwrite:
        logger.error(
            "ERROR: project files exist at %s but no checkpoint found. "
            "Run with --overwrite to replace, or remove the directory manually.",
            project_path,
        )
        return EXIT_STRUCTURAL

    if args.overwrite and checkpoint_path(design).exists():
        logger.warning("Overwrite: clearing checkpoint")
        checkpoint_path(design).unlink(missing_ok=True)
        state = {"completed_steps": []}

    reset_rule4_state()
    mcu_pins = parse_pins(design["mcu"], design["mcu_package"])

    # --- Step: create_project ---
    if not step_done(state, "create_project"):
        client.execute(
            "create_project",
            {
                "project_name": design["project_name"],
                "project_path": design["project_path"],
            },
        )
        state["project_file"] = str(project_file)
        mark_step(state, "create_project")
        save_checkpoint(design, state)

    def structural_4():
        checks = [
            CheckResult(project_file.exists(), "project_file missing"),
            CheckResult(project_file.suffix == ".PrjPcb", "not .PrjPcb"),
        ]
        if project_file.exists():
            text = project_file.read_text(encoding="utf-8", errors="ignore")
            checks.append(CheckResult("[Design]" in text, "invalid PrjPcb INI skeleton"))
            checks.append(CheckResult("Version=1.0" in text, "missing Version=1.0"))
        failed = next((c for c in checks if not c.passed), None)
        return CheckResult(failed is None, failed.message if failed else "")

    if not args.dry_run:
        verify_step(client, "create_project", [structural_4])

    # --- create_schlib ---
    if not step_done(state, "create_schlib"):
        r = client.execute(
            "create_schematic_library",
            {"lib_name": design["project_name"], "project_file_path": design["project_path"]},
        )
        state["lib_path"] = r["result"].get("lib_path", sym_lib)
        mark_step(state, "create_schlib")
        save_checkpoint(design, state)

    # --- footprints ---
    if not step_done(state, "footprints"):
        client.execute(
            "create_pcb_library",
            {"lib_name": "footprints", "project_file_path": design["project_path"]},
        )
        create_all_footprints(client.execute, verbose=not args.dry_run)
        mark_step(state, "footprints")
        save_checkpoint(design, state)

    # --- focus schlib + symbols ---
    if not step_done(state, "symbols"):
        client.execute("focus_document", {"document_path": state.get("lib_path", sym_lib)})
        create_symbols(client, design, mcu_pins)
        mark_step(state, "symbols")
        save_checkpoint(design, state)

    # --- schematic sheet ---
    if not step_done(state, "create_sheet"):
        client.execute(
            "create_schematic_sheet",
            {"sheet_name": "Schematic", "project_file_path": design["project_path"]},
        )
        state["sheet_path"] = str(sheet_path)
        mark_step(state, "create_sheet")
        save_checkpoint(design, state)

    def structural_5():
        ok = sheet_path.exists()
        return CheckResult(ok, "Schematic.SchDoc missing")

    if not args.dry_run:
        verify_step(client, "create_sheet", [structural_5])

    # --- pcb doc ---
    if not step_done(state, "create_pcb"):
        client.execute(
            "create_pcb_document",
            {"pcb_name": "PCB", "project_file_path": design["project_path"]},
        )
        mark_step(state, "create_pcb")
        save_checkpoint(design, state)

    # --- place components ---
    if not step_done(state, "place_component"):
        placements = build_component_placement_list(design)
        existing: set[str] = set()
        if not args.dry_run:
            try:
                data = client.execute("get_schematic_data", {})
                comps = data.get("result", [])
                if isinstance(comps, str):
                    comps = json.loads(comps)
                existing = {c.get("designator") for c in comps if c.get("designator")}
            except Exception:
                pass
        for pl in placements:
            if pl["designator"] in existing:
                logger.info("Skip existing %s", pl["designator"])
                continue
            client.execute_safe(
                "place_component",
                {
                    "library_path": pl["library_path"],
                    "symbol_name": pl["symbol_name"],
                    "designator": pl["designator"],
                    "x": pl["x"],
                    "y": pl["y"],
                },
            )
        mark_step(state, "place_component")
        save_checkpoint(design, state)

    def structural_7():
        exp = expected_designators(design)
        try:
            data = client.execute("get_schematic_data", {})
            comps = data.get("result", [])
            if isinstance(comps, str):
                comps = json.loads(comps)
            des = sorted(c.get("designator") for c in comps if c.get("designator"))
            if sorted(exp) != des:
                return CheckResult(False, f"designators {des} != expected {exp}")
            pin_r = client.execute("get_sch_component_pin_count", {"designator": "U1"})
            cnt = pin_r.get("result", {}).get("pin_count", 0)
            need = resolve_mcu_pin_count(design)
            if cnt != need:
                return CheckResult(False, f"U1 pin_count {cnt} != {need}")
            return CheckResult(True, "")
        except Exception as exc:
            return CheckResult(False, str(exc))

    if not args.dry_run:
        verify_step(
            client,
            "place_component",
            [structural_7],
            ["rule1_canvas", "rule2_overlap", "rule3_designator", "rule4_isolation", "rule7_edge"],
        )

    # --- nets ---
    if not step_done(state, "net_labels"):
        labels = build_net_label_assignments(design, mcu_pins)
        power = build_power_port_assignments(design)
        client.execute("place_net_labels", {"assignments": labels})
        client.execute("place_power_ports", {"assignments": power})
        mark_step(state, "net_labels")
        save_checkpoint(design, state)

    if not args.dry_run:
        unconn = client.execute("get_unconnected_pins", {})
        result = unconn.get("result", [])
        if isinstance(result, str):
            result = json.loads(result)
        count = len(result) if isinstance(result, list) else 0
        if count != 0:
            raise StepVerificationError("unconnected_pins", f"count={count} pins={result}")

        verify_step(client, "net_labels", [], ["rule5_power", "rule6_labels"])

    # --- footprints assign ---
    if not step_done(state, "assign_footprint"):
        for pl in build_component_placement_list(design):
            des = pl["designator"]
            sym = pl["symbol_name"]
            fp = design["footprints"].get(sym) or design["footprints"].get(design["mcu"], "")
            if not fp:
                continue
            client.execute_safe(
                "assign_footprint",
                {
                    "designator": des,
                    "footprint_ref": fp,
                    "footprint_library_path": fp_lib,
                },
            )
        mark_step(state, "assign_footprint")
        save_checkpoint(design, state)

    # --- sync pcb ---
    if not step_done(state, "sync_to_pcb"):
        client.execute("sync_to_pcb", {})
        mark_step(state, "sync_to_pcb")
        save_checkpoint(design, state)

    def structural_9():
        ok = pcb_path.exists() and pcb_path.stat().st_size > 1024
        return CheckResult(ok, "PCB file missing or empty")

    if not args.dry_run:
        verify_step(client, "sync_to_pcb", [structural_9])

    logger.info("Build complete: %s", project_file)
    logger.info("Exit code: %s", exit_code)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StepVerificationError as e:
        logger.error("STRUCTURAL FAILURE: %s", e)
        sys.exit(EXIT_STRUCTURAL)
