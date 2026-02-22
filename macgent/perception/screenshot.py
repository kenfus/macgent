import subprocess
import base64
import os
import logging

logger = logging.getLogger("macgent.screenshot")


def take_screenshot(output_path: str = "/tmp/macgent_screenshot.png") -> str:
    """Capture full screen to file."""
    subprocess.run(["screencapture", "-x", output_path], check=True, timeout=5)
    return output_path


def take_safari_window_screenshot(output_path: str = "/tmp/macgent_safari.png") -> str:
    """Capture just the Safari window region."""
    try:
        bounds = subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to get bounds of front window'],
            capture_output=True, text=True, timeout=5,
        )
        if bounds.returncode == 0:
            parts = bounds.stdout.strip().split(", ")
            x, y, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            w, h = x2 - x, y2 - y
            subprocess.run(
                ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", output_path],
                check=True, timeout=5,
            )
            return output_path
    except Exception as e:
        logger.warning(f"Window screenshot failed, falling back to full screen: {e}")

    return take_screenshot(output_path)


def resize_screenshot(path: str, max_width: int = 1024) -> str:
    """Resize using sips (macOS built-in). Returns resized path."""
    resized_path = path.replace(".png", "_resized.png")
    subprocess.run(
        ["sips", "--resampleWidth", str(max_width), path, "--out", resized_path],
        capture_output=True, timeout=10,
    )
    if os.path.exists(resized_path):
        return resized_path
    return path


def screenshot_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")
