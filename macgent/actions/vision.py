"""Vision helpers: image preprocessing and annotation for vision model input.

These utilities prepare screenshots for submission to vision LLMs (kimi-k2.5,
etc.) by burning coordinate grids, boosting contrast/sharpness, detecting
CAPTCHA tile boundaries, and encoding images as base64.
"""

import io
import logging
import re
from pathlib import Path
import base64
import mimetypes
from typing import Any, Optional

logger = logging.getLogger("macgent.actions.vision")

_DEFAULT_VISION_CLIENT = None


def _get_default_vision_client():
    """Build and cache the default vision fallback client from runtime config."""
    from macgent.config import Config
    from macgent.reasoning.llm_client import build_vision_fallback_client

    global _DEFAULT_VISION_CLIENT
    if _DEFAULT_VISION_CLIENT is None:
        cfg = Config.from_env()
        _DEFAULT_VISION_CLIENT = build_vision_fallback_client(cfg)
        models = [o.model for o in getattr(_DEFAULT_VISION_CLIENT, "offers", [])]
        logger.info("call_vision using offers: %s", models)
    return _DEFAULT_VISION_CLIENT


def _coerce_image_input(image: Any, media_type: str) -> tuple[str, str]:
    """Normalize image input to (image_base64, media_type)."""
    if isinstance(image, bytes):
        return base64.b64encode(image).decode("ascii"), media_type

    if isinstance(image, str):
        s = image.strip()
        if s.startswith("data:") and ";base64," in s:
            prefix, payload = s.split("base64,", 1)
            mt = media_type
            if prefix.startswith("data:"):
                mt = prefix[5:].split(";", 1)[0] or media_type
            return payload, mt

        p = Path(s)
        if p.exists() and p.is_file():
            mt = mimetypes.guess_type(p.name)[0] or media_type
            return base64.b64encode(p.read_bytes()).decode("ascii"), mt

        # Assume caller already provided raw base64.
        return s, media_type

    # PIL Image-like object
    if hasattr(image, "save"):
        return image_to_base64(image), media_type

    raise TypeError(
        "image must be bytes, base64/data-url string, filesystem path string, or PIL Image"
    )


def call_vision(
    image: Any,
    prompt: str,
    *,
    media_type: str = "image/png",
    max_tokens: int = 1024,
    system: Optional[str] = None,
    client=None,
) -> str:
    """Generic vision call helper: image + prompt -> model response text.

    `image` may be:
    - bytes
    - base64 string (no prefix)
    - data URL string (`data:image/png;base64,...`)
    - filesystem path string
    - PIL Image object
    """
    image_b64, resolved_media_type = _coerce_image_input(image, media_type)
    vision_client = client or _get_default_vision_client()
    return vision_client.chat_with_image(
        prompt=prompt,
        image_base64=image_b64,
        image_media_type=resolved_media_type,
        system=system,
        max_tokens=max_tokens,
    )


def annotate_image(
    img,
    origin_x: int = 0,
    origin_y: int = 0,
    grid_step: int = 50,
    scale: float = 1.0,
):
    """Burn an absolute-coordinate grid onto a PIL Image and return the result.

    origin_x / origin_y: screen-coordinate of the top-left pixel of *img*.
    grid_step: spacing in logical (screen) pixels between grid lines.
    scale: image pixels per logical point (1.0 for non-Retina, 2.0 for Retina).

    Returns a new RGB PIL Image with the grid overlay composited on top.
    The coordinate labels embedded in the image allow vision models to read off
    exact positions without any additional arithmetic.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = img.convert("RGBA")
    iw, ih = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(10, int(11 * scale))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

    def _outlined_text(draw, pos, text, font):
        x, y = pos
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, fill=(0, 0, 0, 255), font=font)
        draw.text((x, y), text, fill=(255, 255, 80, 255), font=font)

    grid_px = max(1, int(grid_step * scale))
    for ix in range(0, iw + grid_px, grid_px):
        px = min(ix, iw - 1)
        abs_x = origin_x + round(px / scale)
        draw.line([(px, 0), (px, ih)], fill=(255, 80, 80, 110), width=1)
        _outlined_text(draw, (px + 2, 2), str(abs_x), font)

    for iy in range(0, ih + grid_px, grid_px):
        py = min(iy, ih - 1)
        abs_y = origin_y + round(py / scale)
        draw.line([(0, py), (iw, py)], fill=(255, 80, 80, 110), width=1)
        _outlined_text(draw, (2, py + 2), str(abs_y), font)

    return Image.alpha_composite(img, overlay).convert("RGB")


def enhance_for_vision(img, contrast: float = 1.5, sharpness: float = 1.3):
    """Boost contrast and sharpness to help vision models read fine details.

    Useful before passing a CAPTCHA screenshot to a vision LLM.
    Returns a new PIL Image.
    """
    from PIL import ImageEnhance
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return img


def image_to_base64(img, fmt: str = "PNG") -> str:
    """Encode a PIL Image to a base64 string (no data-URL prefix)."""
    import base64
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def annotate_image_rowcol(
    img,
    cell_size: int = 80,
    grayscale: bool = True,
    label: bool = True,
):
    """Draw a square-cell grid onto a PIL Image with chess-style labels (A1, B3, …).

    cell_size: side length in pixels for each square cell.  Rows and cols are
               computed from the image dimensions so cells are always square.
               rows = ceil(height / cell_size), cols = ceil(width / cell_size).

    grayscale: convert to greyscale + boost contrast before annotating.
               Reduces visual noise so grid labels stand out clearly.

    label: draw "A1"-style labels at each cell center (letter=row, digit=col).

    Returns (annotated_img, cell_centers) where
        cell_centers[r][c] = (cx_px, cy_px)  — pixel center of row r, col c (0-indexed).

    Vision models answer "cell B3" or "cells C4, D4" — unambiguous, no pixel arithmetic.
    Caller converts: cell_centers[row_idx][col_idx] → (x, y) to click.
    """
    import math
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    if grayscale:
        img = ImageOps.grayscale(img).convert("RGB")
        img = ImageEnhance_contrast(img, 1.8)

    img = img.convert("RGBA")
    iw, ih = img.size

    cols = math.ceil(iw / cell_size)
    rows = math.ceil(ih / cell_size)
    cell_w = iw / cols
    cell_h = ih / rows

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(9, int(cell_size * 0.22))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

    LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # Grid lines — semi-transparent red
    for c in range(1, cols):
        x = int(c * cell_w)
        draw.line([(x, 0), (x, ih)], fill=(220, 60, 60, 140), width=1)
    for r in range(1, rows):
        y = int(r * cell_h)
        draw.line([(0, y), (iw, y)], fill=(220, 60, 60, 140), width=1)

    # Labels and cell centers
    cell_centers: list[list[tuple[int, int]]] = []
    for r in range(rows):
        row_centers = []
        for c in range(cols):
            cx = int((c + 0.5) * cell_w)
            cy = int((r + 0.5) * cell_h)
            row_centers.append((cx, cy))
            if label:
                row_letter = LETTERS[r % 26] if r < 26 else f"{LETTERS[r // 26 - 1]}{LETTERS[r % 26]}"
                text = f"{row_letter}{c + 1}"
                # Black outline for readability on any background
                for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, -1), (0, 1), (-1, 0), (1, 0)):
                    draw.text((cx + dx, cy + dy), text, fill=(0, 0, 0, 255), font=font, anchor="mm")
                draw.text((cx, cy), text, fill=(255, 255, 60, 255), font=font, anchor="mm")
        cell_centers.append(row_centers)

    annotated = Image.alpha_composite(img, overlay).convert("RGB")
    return annotated, cell_centers, rows, cols


def _parse_chess_cell(label: str) -> tuple[int, int] | None:
    """Parse a chess-style cell label like 'A1', 'B3', 'C12' → (row_idx, col_idx) 0-indexed.

    Returns None if the label cannot be parsed.
    """
    import re
    m = re.match(r"^([A-Z]{1,2})(\d+)$", label.strip().upper())
    if not m:
        return None
    letters, num = m.group(1), int(m.group(2)) - 1
    LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if len(letters) == 1:
        row = LETTERS.index(letters)
    else:
        row = (LETTERS.index(letters[0]) + 1) * 26 + LETTERS.index(letters[1])
    return (row, num)


def _parse_chess_cells_from_text(text: str) -> list[tuple[int, int]]:
    """Extract all chess-style cell references (A1, B3, C12…) from model response text.

    Returns list of (row_idx, col_idx) tuples, 0-indexed, deduplicated.
    """
    import re
    raw = re.findall(r"\b([A-Z]{1,2}\d{1,2})\b", text.upper())
    seen: set[tuple[int, int]] = set()
    result = []
    for label in raw:
        parsed = _parse_chess_cell(label)
        if parsed and parsed not in seen:
            seen.add(parsed)
            result.append(parsed)
    return result


def ImageEnhance_contrast(img, factor: float):
    """Helper: boost contrast on an RGB PIL image."""
    from PIL import ImageEnhance
    return ImageEnhance.Contrast(img).enhance(factor)


def detect_tile_grid(img, min_tiles: int = 3, max_tiles: int = 6,
                     line_thickness: int = 6):
    """Detect the tile grid of a CAPTCHA image using intensity profiling.

    Works on Google reCAPTCHA-style grids (3×3, 4×4) where tiles are separated
    by thin bright or dark lines/gaps.  No OpenCV needed — pure PIL pixel math.

    Algorithm:
      1. Convert to grayscale
      2. Compute per-column / per-row average brightness profiles
      3. Find "peak lines" — narrow bands where brightness is much higher
         (or lower) than the local neighbourhood on both sides
      4. Cluster nearby peaks → divider center positions
      5. Pick the best evenly-spaced set of dividers for min_tiles..max_tiles

    The peak-based approach works for both bright dividers (white lines between
    tiles) and dark dividers (dark gaps between tiles).

    Args:
        img: PIL Image of the cropped CAPTCHA region.
        min_tiles: minimum expected tiles per axis (3 for 3×3).
        max_tiles: maximum expected tiles per axis (6 for 4×4 with margin).
        line_thickness: max width in px of a divider line.

    Returns:
        tiles: list of (x0, y0, x1, y1) pixel bounding boxes for each tile,
               ordered left-to-right, top-to-bottom.
        grid_shape: (n_rows, n_cols) detected grid dimensions.
        dividers_x: list of x positions of vertical dividers.
        dividers_y: list of y positions of horizontal dividers.

    Returns ([], (0,0), [], []) if no grid detected.
    """
    from PIL import ImageOps

    gray = ImageOps.grayscale(img)
    w, h = gray.size

    # Build per-column and per-row average brightness using PIL
    col_avg = []
    for x in range(w):
        total = 0
        for y in range(h):
            total += gray.getpixel((x, y))
        col_avg.append(total / h)

    row_avg = []
    for y in range(h):
        total = 0
        for x in range(w):
            total += gray.getpixel((x, y))
        row_avg.append(total / w)

    def _find_dividers(profile: list[float], length: int,
                       thickness: int, min_t: int, max_t: int) -> list[int]:
        """Find divider positions using local-contrast peak detection.

        A divider line stands out from its surroundings: it's either much
        brighter or much darker than the pixels ~10px away on each side.
        We compute a "local contrast" score for each position and find peaks.
        """
        if length < 30:
            return []

        # Local contrast: how different is this position from its neighbourhood?
        # Compare each position's brightness to the average of positions ±window away
        window = max(8, length // 30)  # ~10-20px neighbourhood
        contrast = []
        for i in range(length):
            left_start = max(0, i - window * 2)
            left_end = max(0, i - window // 2)
            right_start = min(length, i + window // 2)
            right_end = min(length, i + window * 2)

            left_vals = profile[left_start:left_end] if left_end > left_start else []
            right_vals = profile[right_start:right_end] if right_end > right_start else []
            neighbors = left_vals + right_vals

            if neighbors:
                neighbor_avg = sum(neighbors) / len(neighbors)
                contrast.append(abs(profile[i] - neighbor_avg))
            else:
                contrast.append(0.0)

        # Find positions with high local contrast
        sorted_contrast = sorted(contrast, reverse=True)
        # Adaptive threshold: top values, but at least 20
        top_idx = max(1, length // 40)
        threshold = max(20.0, sorted_contrast[top_idx] * 0.4)

        peak_positions: list[int] = []
        for i, c in enumerate(contrast):
            if c >= threshold:
                peak_positions.append(i)

        if not peak_positions:
            return []

        # Cluster nearby peaks into divider centers
        clusters: list[list[int]] = []
        current_cluster = [peak_positions[0]]
        for i in range(1, len(peak_positions)):
            if peak_positions[i] - peak_positions[i-1] <= thickness:
                current_cluster.append(peak_positions[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [peak_positions[i]]
        clusters.append(current_cluster)

        # Divider center = middle of each cluster
        centers = [sum(c) // len(c) for c in clusters]

        # Try each possible tile count and score by how evenly-spaced the
        # dividers are.  Pick the configuration with the best uniformity.
        overall_best = None
        overall_best_score = float('inf')

        for n_tiles in range(min_t, max_t + 1):
            n_dividers = n_tiles - 1
            if len(centers) < n_dividers:
                continue

            # Try subsets of centers as dividers
            for start_c in range(len(centers)):
                for end_c in range(start_c + n_dividers - 1, len(centers)):
                    region_start = centers[start_c]
                    region_end = centers[end_c]
                    span = region_end - region_start
                    if span < length * 0.3:
                        continue

                    expected_spacing = span / (n_dividers - 1) if n_dividers > 1 else span
                    expected = [int(region_start + expected_spacing * k)
                                for k in range(n_dividers)]

                    matched = []
                    used = set()
                    total_error = 0
                    for exp_pos in expected:
                        best_dist = length
                        best_idx = -1
                        for ci, c in enumerate(centers):
                            if ci not in used:
                                dist = abs(c - exp_pos)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_idx = ci
                        if best_idx >= 0 and best_dist < expected_spacing * 0.25:
                            matched.append(centers[best_idx])
                            used.add(best_idx)
                            total_error += best_dist
                        else:
                            break

                    if len(matched) != n_dividers:
                        continue

                    matched = sorted(matched)

                    # Score: coefficient of variation of tile sizes
                    # (lower = more uniform = better)
                    tile_size_estimate = span / n_dividers
                    if tile_size_estimate < 20:
                        continue

                    # Compute actual tile sizes including edge tiles
                    edges = [max(0, int(matched[0] - tile_size_estimate))]
                    edges.extend(matched)
                    edges.append(min(length, int(matched[-1] + tile_size_estimate)))
                    sizes = [edges[i+1] - edges[i] for i in range(len(edges)-1)]
                    mean_size = sum(sizes) / len(sizes)
                    if mean_size < 1:
                        continue
                    variance = sum((s - mean_size) ** 2 for s in sizes) / len(sizes)
                    cv = (variance ** 0.5) / mean_size  # coefficient of variation

                    # Penalize: smaller grids slightly (prefer 4×4 over 3×3)
                    # and uneven tiles heavily
                    score = cv + total_error / (n_dividers * length)

                    if score < overall_best_score:
                        overall_best_score = score
                        overall_best = matched

        return overall_best or []

    dividers_x = _find_dividers(col_avg, w, line_thickness, min_tiles, max_tiles)
    dividers_y = _find_dividers(row_avg, h, line_thickness, min_tiles, max_tiles)

    if not dividers_x or not dividers_y:
        logger.warning("detect_tile_grid: could not detect grid dividers "
                       f"(found {len(dividers_x)} vertical, {len(dividers_y)} horizontal)")
        return [], (0, 0), [], []

    n_cols = len(dividers_x) + 1
    n_rows = len(dividers_y) + 1

    # Build tile bounding boxes — use the region between first and last divider
    # as the grid, with edges extending to image boundaries
    first_div_x = dividers_x[0]
    last_div_x = dividers_x[-1]
    first_div_y = dividers_y[0]
    last_div_y = dividers_y[-1]

    # Estimate tile size from divider spacing
    tile_w = (last_div_x - first_div_x) / (n_cols - 2) if n_cols > 2 else last_div_x - first_div_x
    tile_h = (last_div_y - first_div_y) / (n_rows - 2) if n_rows > 2 else last_div_y - first_div_y

    # Grid edges: extend half a tile before first divider and after last
    x0_edge = max(0, int(first_div_x - tile_w))
    x1_edge = min(w, int(last_div_x + tile_w))
    y0_edge = max(0, int(first_div_y - tile_h))
    y1_edge = min(h, int(last_div_y + tile_h))

    x_edges = [x0_edge] + dividers_x + [x1_edge]
    y_edges = [y0_edge] + dividers_y + [y1_edge]

    tiles = []
    for ri in range(n_rows):
        for ci in range(n_cols):
            tiles.append((x_edges[ci], y_edges[ri], x_edges[ci + 1], y_edges[ri + 1]))

    logger.info(f"detect_tile_grid: found {n_rows}×{n_cols} grid, "
                f"dividers_x={dividers_x}, dividers_y={dividers_y}, "
                f"grid_region=({x0_edge},{y0_edge})-({x1_edge},{y1_edge})")
    return tiles, (n_rows, n_cols), dividers_x, dividers_y


def label_detected_tiles(img, tiles: list[tuple[int, int, int, int]],
                         grid_shape: tuple[int, int],
                         grayscale: bool = True):
    """Annotate an image with chess labels on detected tile centers.

    Unlike annotate_image_rowcol (which uses arbitrary cell sizes), this uses
    the actual detected tile boundaries so each label maps 1:1 to a real
    clickable CAPTCHA tile.

    Args:
        img: PIL Image (the cropped CAPTCHA).
        tiles: list of (x0, y0, x1, y1) from detect_tile_grid.
        grid_shape: (n_rows, n_cols).
        grayscale: convert to greyscale + contrast boost.

    Returns:
        (annotated_img, tile_centers) where
        tile_centers[r][c] = (cx, cy) pixel center of tile at row r, col c.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    if grayscale:
        img = ImageOps.grayscale(img).convert("RGB")
        img = ImageEnhance_contrast(img, 1.8)

    img = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    n_rows, n_cols = grid_shape
    LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # Estimate font size from average tile size
    avg_tile_w = img.size[0] / max(n_cols, 1)
    font_size = max(12, int(avg_tile_w * 0.2))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

    # Draw tile boundaries
    for x0, y0, x1, y1 in tiles:
        draw.rectangle([x0, y0, x1, y1], outline=(220, 60, 60, 180), width=2)

    # Labels at tile centers
    tile_centers: list[list[tuple[int, int]]] = []
    for r in range(n_rows):
        row_centers = []
        for c in range(n_cols):
            idx = r * n_cols + c
            x0, y0, x1, y1 = tiles[idx]
            cx = (x0 + x1) // 2
            cy = (y0 + y1) // 2
            row_centers.append((cx, cy))

            row_letter = LETTERS[r % 26] if r < 26 else f"{LETTERS[r // 26 - 1]}{LETTERS[r % 26]}"
            text = f"{row_letter}{c + 1}"
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, -1), (0, 1), (-1, 0), (1, 0)):
                draw.text((cx + dx, cy + dy), text, fill=(0, 0, 0, 255), font=font, anchor="mm")
            draw.text((cx, cy), text, fill=(255, 255, 60, 255), font=font, anchor="mm")
        tile_centers.append(row_centers)

    annotated = Image.alpha_composite(img, overlay).convert("RGB")
    return annotated, tile_centers


def annotate_and_save(
    src_path: str,
    dst_path: str | None = None,
    origin_x: int = 0,
    origin_y: int = 0,
    grid_step: int = 50,
    contrast: float = 1.0,
    sharpness: float = 1.0,
) -> str:
    """Load an existing image, optionally enhance it, burn a grid, and save.

    Useful for annotating agent-browser or Playwright screenshots before
    sending to a vision model.  dst_path defaults to src_path (in-place).
    """
    from PIL import Image
    img = Image.open(src_path)
    if contrast != 1.0 or sharpness != 1.0:
        img = enhance_for_vision(img, contrast=contrast, sharpness=sharpness)
    img = annotate_image(img, origin_x=origin_x, origin_y=origin_y, grid_step=grid_step)
    out = dst_path or src_path
    img.save(out)
    return out
