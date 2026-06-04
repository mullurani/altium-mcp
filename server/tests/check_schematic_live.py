"""Live check: bridge + schematic tools with Altium open."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import altium_bridge


async def main():
    print("=== get_server_status (config paths) ===")
    from main import altium_bridge as ab
    import os
    cfg = ab.config
    print(json.dumps({
        "altium_exe": cfg.altium_exe_path,
        "altium_exists": os.path.exists(cfg.altium_exe_path),
        "script_exists": os.path.exists(cfg.script_path),
    }, indent=2))

    print("\n=== get_schematic_data (all components on sheet) ===")
    r = await altium_bridge.execute_command("get_schematic_data", {})
    if not r.get("success"):
        print("FAILED:", json.dumps(r, indent=2))
        return 1
    data = r.get("result", [])
    if isinstance(data, str):
        data = json.loads(data)
    if isinstance(data, list):
        designators = [c.get("designator") for c in data[:15] if isinstance(c, dict)]
        print(f"Found {len(data)} component(s). First designators: {designators}")
    else:
        print(json.dumps(data, indent=2)[:1500])

    print("\n=== get_unconnected_pins (sample) ===")
    r2 = await altium_bridge.execute_command("get_unconnected_pins", {})
    if not r2.get("success"):
        print("FAILED:", json.dumps(r2, indent=2))
        return 1
    pins = r2.get("result", [])
    if isinstance(pins, str):
        pins = json.loads(pins)
    print(f"Unconnected pins count: {len(pins) if isinstance(pins, list) else 'n/a'}")
    if isinstance(pins, list) and pins:
        print("Sample:", json.dumps(pins[:5], indent=2))

    print("\nOK: Altium schematic bridge is responding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
