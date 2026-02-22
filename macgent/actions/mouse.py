import subprocess
import logging

logger = logging.getLogger("macgent.actions.mouse")

CLICLICK = "/opt/homebrew/bin/cliclick"


def mouse_click(x: int, y: int) -> str:
    subprocess.run([CLICLICK, f"c:{x},{y}"], check=True, timeout=5)
    return f"Clicked at ({x}, {y})"


def mouse_double_click(x: int, y: int) -> str:
    subprocess.run([CLICLICK, f"dc:{x},{y}"], check=True, timeout=5)
    return f"Double-clicked at ({x}, {y})"


def mouse_move(x: int, y: int) -> str:
    subprocess.run([CLICLICK, f"m:{x},{y}"], check=True, timeout=5)
    return f"Moved mouse to ({x}, {y})"
