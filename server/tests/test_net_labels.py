"""
Manual integration test for place_net_labels.
Run from the repo root with the venv Python:
    server\\.venv\\Scripts\\python.exe server/tests/test_net_labels.py

Requires: Altium open with a .SchDoc focused.
Replace designator/pin values with real ones from your open schematic.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import altium_bridge


async def test_place_net_labels():
    r = await altium_bridge.execute_command("place_net_labels", {
        "assignments": [
            "U1|VCC|3V3",  # replace with real designator|pin|net from your schematic
            "U2|VCC|3V3",
        ]
    })
    print(json.dumps(r, indent=2))
    assert r.get("success"), f"Expected success, got: {r}"
    print("PASS: net labels placed")


if __name__ == "__main__":
    asyncio.run(test_place_net_labels())
