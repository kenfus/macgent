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
    """
    Take a screenshot (optionally of a region), then burn an absolute-coordinate
    grid onto it. Labels show screen coordinates so callers can read off the exact
    position of any visible UI element without guessing.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Capture
    if w and h:
        subprocess.run(
            ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path],
            check=True, timeout=10,
        )
        origin_x, origin_y = x, y
    else:
        subprocess.run(["screencapture", "-x", path], check=True, timeout=10)
        origin_x, origin_y = 0, 0

    img = Image.open(path).convert("RGBA")
    iw, ih = img.size

    # Scale factor: image pixels per logical point (1x or 2x Retina)
    scale = iw / w if w else 1.0

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", max(10, int(11 * scale)))
    except Exception:
        font = ImageFont.load_default()

    def _draw_outlined_text(draw, pos, text, font):
        """Draw text with a dark outline so it's readable on any background."""
        x, y = pos
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, fill=(0, 0, 0, 255), font=font)
        draw.text((x, y), text, fill=(255, 255, 80, 255), font=font)

    # Draw grid lines and coordinate labels
    grid_px = int(grid_step * scale)
    for ix in range(0, iw + grid_px, grid_px):
        px = min(ix, iw - 1)
        abs_x = origin_x + round(px / scale)
        draw.line([(px, 0), (px, ih)], fill=(255, 80, 80, 110), width=1)
        _draw_outlined_text(draw, (px + 2, 2), str(abs_x), font)

    for iy in range(0, ih + grid_px, grid_px):
        py = min(iy, ih - 1)
        abs_y = origin_y + round(py / scale)
        draw.line([(0, py), (iw, py)], fill=(255, 80, 80, 110), width=1)
        _draw_outlined_text(draw, (2, py + 2), str(abs_y), font)

    combined = Image.alpha_composite(img, overlay).convert("RGB")
    combined.save(path)
    return f"Annotated screenshot saved: {path} (grid_step={grid_step}px, origin=({origin_x},{origin_y}))"
