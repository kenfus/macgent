"""Shared AppleScript execution utility for macOS actions."""

import subprocess
import time
import logging

logger = logging.getLogger("macgent.osascript")


def run_osascript(script: str, timeout: int = 15) -> str:
    """Execute AppleScript and return stdout. Retries once on timeout."""
    for attempt in range(2):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            if attempt == 0:
                logger.warning(f"osascript timed out after {timeout}s, retrying...")
                time.sleep(1)
                timeout = timeout * 2
                continue
            raise RuntimeError(f"osascript timed out after {timeout}s")
