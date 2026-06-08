"""
Standalone Altium bridge (no MCP dependency) for build.py and CLI tools.
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("AltiumBridge")

MCP_DIR = Path(__file__).parent
CONFIG_FILE = MCP_DIR / "config.json"
DEFAULT_SCRIPT_PATH = MCP_DIR / "AltiumScript" / "Altium_API.PrjScr"
EXCHANGE_DIR = Path("C:/Users/Public/altium_mcp")
EXCHANGE_DIR.mkdir(exist_ok=True)
REQUEST_FILE = EXCHANGE_DIR / "request.json"
RESPONSE_FILE = EXCHANGE_DIR / "response.json"
SCRIPT_LOCK_FILE = EXCHANGE_DIR / "script.lock"
COMMAND_GAP_S = 2.0
SCRIPT_START_TIMEOUT_S = 45.0
SCRIPT_RUN_TIMEOUT_S = 180.0
STALE_LOCK_AGE_S = 180.0


class AltiumConfig:
    def __init__(self):
        self.altium_exe_path = ""
        self.script_path = str(DEFAULT_SCRIPT_PATH)
        self.load_config()

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.altium_exe_path = config.get("altium_exe_path", "")
                    self.script_path = config.get("script_path", str(DEFAULT_SCRIPT_PATH))
            except Exception as e:
                logger.error("Error loading configuration: %s", e)
        else:
            self._discover_altium_exe()

    def _discover_altium_exe(self):
        altium_base_path = r"C:\Program Files\Altium"
        if os.path.exists(altium_base_path):
            ad_dirs = glob.glob(os.path.join(altium_base_path, "AD*"))

            def get_version_number(dir_path):
                match = re.search(r"AD(\d+)", os.path.basename(dir_path))
                return int(match.group(1)) if match else 0

            ad_dirs.sort(key=get_version_number, reverse=True)
            for ad_dir in ad_dirs:
                potential_exe = os.path.join(ad_dir, "X2.EXE")
                if os.path.exists(potential_exe):
                    self.altium_exe_path = potential_exe
                    break

    def verify_paths(self) -> bool:
        return bool(self.altium_exe_path and os.path.exists(self.altium_exe_path))


class AltiumBridge:
    def __init__(self):
        self.config = AltiumConfig()
        self.config.verify_paths()
        self._last_process: subprocess.Popen | None = None

    def cleanup_after_failure(self, reason: str = "") -> None:
        """Release bridge state so the next RunScript can start cleanly."""
        if reason:
            logger.warning("Cleaning up after bridge failure: %s", reason)

        if self._last_process is not None:
            try:
                if self._last_process.poll() is None:
                    self._last_process.terminate()
                    try:
                        self._last_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._last_process.kill()
                        self._last_process.wait(timeout=2)
            except Exception as exc:
                logger.debug("Could not terminate launcher process: %s", exc)
            finally:
                self._last_process = None

        if SCRIPT_LOCK_FILE.exists():
            try:
                SCRIPT_LOCK_FILE.unlink()
            except OSError as exc:
                logger.debug("Could not remove script lock: %s", exc)

    async def _wait_for_script_idle(self, timeout: float = SCRIPT_RUN_TIMEOUT_S) -> None:
        """Wait for the in-Altium script to finish (lock file cleared)."""
        if not SCRIPT_LOCK_FILE.exists():
            return

        logger.info("Waiting for previous Altium script to finish...")
        start = time.time()
        while SCRIPT_LOCK_FILE.exists() and time.time() - start < timeout:
            await asyncio.sleep(0.5)

        if SCRIPT_LOCK_FILE.exists():
            age = time.time() - SCRIPT_LOCK_FILE.stat().st_mtime
            if age >= STALE_LOCK_AGE_S:
                logger.warning(
                    "Script lock stale (age %.0fs); clearing lock file",
                    age,
                )
                try:
                    SCRIPT_LOCK_FILE.unlink()
                except OSError as exc:
                    logger.debug("Could not remove stale script lock: %s", exc)
            else:
                logger.warning(
                    "Script lock still held (age %.0fs). "
                    "If Altium shows 'Another script executing', click OK and wait "
                    "for the current script to finish before retrying.",
                    age,
                )

    async def _wait_for_script_start(self, timeout: float = SCRIPT_START_TIMEOUT_S) -> bool:
        """Return True once the Altium Run procedure creates script.lock."""
        if SCRIPT_LOCK_FILE.exists():
            return True
        start = time.time()
        while not SCRIPT_LOCK_FILE.exists() and time.time() - start < timeout:
            await asyncio.sleep(0.25)
        return SCRIPT_LOCK_FILE.exists()

    async def execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        last_error = "Unknown error"
        for attempt in range(3):
            try:
                await self._wait_for_script_idle()
                await asyncio.sleep(COMMAND_GAP_S if attempt == 0 else 5.0)

                if RESPONSE_FILE.exists():
                    RESPONSE_FILE.unlink()

                with open(REQUEST_FILE, "w") as f:
                    json.dump({"command": command, **params}, f, indent=2)

                if not await self.run_altium_script():
                    self.cleanup_after_failure("failed to launch Altium script")
                    return {"success": False, "error": "Failed to run Altium script"}

                saw_lock = await self._wait_for_script_start()
                if not saw_lock:
                    logger.warning(
                        "script.lock not created (recompile Altium_API.PrjScr, or dismiss "
                        "'Another script executing' dialogs in Altium). "
                        "Waiting for response.json anyway..."
                    )

                start = time.time()
                while time.time() - start < SCRIPT_RUN_TIMEOUT_S:
                    if RESPONSE_FILE.exists():
                        break
                    if saw_lock and not SCRIPT_LOCK_FILE.exists() and (time.time() - start) > 3.0:
                        break
                    await asyncio.sleep(0.5)

                if saw_lock:
                    await self._wait_for_script_idle(timeout=30.0)

                if not RESPONSE_FILE.exists():
                    last_error = "No response received from Altium (timeout)"
                    self.cleanup_after_failure(last_error)
                    continue

                with open(RESPONSE_FILE, "r") as f:
                    response = json.loads(f.read())

                if not response.get("success", False):
                    self.cleanup_after_failure("Altium returned success=false")

                await asyncio.sleep(COMMAND_GAP_S)
                return response
            except Exception as e:
                last_error = str(e)
                self.cleanup_after_failure(last_error)

        return {"success": False, "error": last_error}

    async def run_altium_script(self) -> bool:
        if not os.path.exists(self.config.altium_exe_path):
            return False
        if not os.path.exists(self.config.script_path):
            return False
        script_path = self.config.script_path
        command = (
            f'"{self.config.altium_exe_path}" -RScriptingSystem:RunScript'
            f'(ProjectName="{script_path}"^|ProcName="Altium_API>Run")'
        )
        self._last_process = subprocess.Popen(command, shell=True)
        return True


altium_bridge = AltiumBridge()
