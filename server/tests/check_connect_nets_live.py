"""Live smoke test for the declarative netlist layer (needs Altium open).

Read-only by default:
    python server/tests/check_connect_nets_live.py [path/to/file.netlist]
      - reads back connectivity (get_pin_nets)
      - parses + validates the netlist against the live schematic
      - previews the auto-mix plan
      - runs check_netlist (diff)

Add --apply to actually place it (and re-apply to prove idempotency):
    python server/tests/check_connect_nets_live.py file.netlist --apply
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import netlist as nm                         # noqa: E402
from main import _read_pin_nets, _apply_netlist_obj  # noqa: E402


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    do_apply = "--apply" in sys.argv
    netlist_path = args[0] if args else None

    print("== get_pin_nets ==")
    data, err = await _read_pin_nets()
    if err:
        print(f"ERROR: {err}")
        return 1
    print(f"{len(data)} pins read; {sum(1 for d in data if d.get('net'))} connected")
    for d in data[:5]:
        print(f"  {d['designator']}.{d['pin_number']} ({d['pin_name']}) -> '{d['net']}'  [{d['sheet']}]")

    if not netlist_path:
        print("\nNo netlist file given; stopping after read-back.")
        return 0

    text = Path(netlist_path).read_text(encoding="utf-8")
    try:
        nl = nm.parse_netlist(text)
    except nm.NetlistError as e:
        print(f"PARSE ERROR: {e}")
        return 1

    index = nm.build_pin_index(data)
    errors = nm.validate(nl, index)
    print(f"\n== validation ==\n{'OK' if not errors else chr(10).join(errors)}")

    print("\n== planned actions ==")
    for a in nm.plan(nl, index):
        print(f"  {a.net:<16} {a.method}")

    print("\n== check_netlist (diff) ==")
    print(nm.diff(nl, data).to_text())

    if do_apply:
        print("\n== apply (1st) ==")
        r1 = await _apply_netlist_obj(nl)
        print(json.dumps(r1.get("summary", r1), indent=2))
        print("\n== apply (2nd; expect skipped_existing) ==")
        data2, _ = await _read_pin_nets()
        r2 = await _apply_netlist_obj(nm.parse_netlist(text))
        print(json.dumps(r2.get("summary", r2), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
