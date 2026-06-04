"""Quick test: place_net_labels on one pin (edit designator|pin|net first)."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import altium_bridge


async def main():
    # EDIT these three fields to match your open schematic
    assignment = "U1|1|TEST_NET_MCP"

    print(f"Testing place_net_labels: {assignment}")
    r = await altium_bridge.execute_command(
        "place_net_labels", {"assignments": [assignment]}
    )
    print(json.dumps(r, indent=2))
    if not r.get("success"):
        return 1
    result = r.get("result", {})
    if isinstance(result, str):
        result = json.loads(result)
    print(f"placed_count={result.get('placed_count')}, skipped={result.get('skipped_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
