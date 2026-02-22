import subprocess
import logging

logger = logging.getLogger("macgent.actions.keyboard")

CLICLICK = "/opt/homebrew/bin/cliclick"


def key_press(key: str) -> str:
    """Press a key via cliclick."""
    subprocess.run([CLICLICK, f"kp:{key}"], check=True, timeout=5)
    return f"Pressed key via cliclick: {key}"


def type_string(text: str) -> str:
    """Type a string via cliclick."""
    subprocess.run([CLICLICK, f"t:{text}"], check=True, timeout=5)
    return f"Typed via cliclick: {text}"
