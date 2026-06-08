"""
Synchronous wrapper around AltiumBridge for build.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

logger = logging.getLogger("build")


class AltiumClient:
    def __init__(self, bridge: Any, *, dry_run: bool = False, verbose: bool = False):
        self.bridge = bridge
        self.dry_run = dry_run
        self.verbose = verbose

    def execute(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if self.dry_run:
            logger.info("[dry-run] %s %s", command, json.dumps(params, indent=2 if self.verbose else None))
            return {"success": True, "result": {"dry_run": True, "command": command}}

        if self.verbose:
            logger.info(">> %s %s", command, json.dumps(params, indent=2))

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(self.bridge.execute_command(command, params))
        finally:
            loop.close()

        if self.verbose:
            logger.info("<< %s", json.dumps(response, indent=2))

        if not response.get("success", False):
            err = response.get("error", "Unknown error")
            result = response.get("result", "")
            if isinstance(result, str) and result.startswith("ERROR:"):
                err = result
            if hasattr(self.bridge, "cleanup_after_failure"):
                self.bridge.cleanup_after_failure(f"{command} failed: {err}")
            raise RuntimeError(f"{command} failed: {err}")

        result = response.get("result", {})
        if isinstance(result, str):
            if result.startswith("ERROR:"):
                if hasattr(self.bridge, "cleanup_after_failure"):
                    self.bridge.cleanup_after_failure(result)
                raise RuntimeError(result)
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                pass
        return {"success": True, "result": result}

    def execute_safe(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return self.execute(command, params)
        except Exception as exc:
            return {"success": False, "error": str(exc)}


def run_with_retry(
    fn: Callable[[], Any],
    *,
    retries: int = 2,
    delay_s: float = 2.0,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(delay_s)
    raise last_exc  # type: ignore[misc]
