import subprocess
import logging

from macgent.actions.vision import annotate_image, enhance_for_vision, image_to_base64, annotate_and_save  # noqa: F401

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


def take_screenshot(path: str) -> str:
    """Take a screenshot and save to path."""
    subprocess.run(["screencapture", "-x", path], check=True, timeout=10)
    return f"Screenshot saved: {path}"


def take_screenshot_region(path: str, x: int, y: int, w: int, h: int) -> str:
    """Take a screenshot of a screen region (absolute logical coordinates)."""
    subprocess.run(
        ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path],
        check=True, timeout=10,
    )
    return f"Screenshot saved: {path}"


def take_annotated_screenshot(
    path: str,
    x: int = 0,
    y: int = 0,
    w: int = 0,
    h: int = 0,
    grid_step: int = 35,
) -> str:
    """Take a macOS screenshot (optionally of a region) and burn a coordinate grid onto it."""
    from PIL import Image

    if w and h:
        subprocess.run(
            ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path],
            check=True, timeout=10,
        )
        origin_x, origin_y = x, y
    else:
        subprocess.run(["screencapture", "-x", path], check=True, timeout=10)
        origin_x, origin_y = 0, 0

    img = Image.open(path)
    iw = img.size[0]
    scale = iw / w if w else 1.0
    annotated = annotate_image(img, origin_x=origin_x, origin_y=origin_y, grid_step=grid_step, scale=scale)
    annotated.save(path)
    return f"Annotated screenshot saved: {path} (grid_step={grid_step}px, origin=({origin_x},{origin_y}))"


