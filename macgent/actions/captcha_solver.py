"""CAPTCHA solver using 3-pass sub-agent pipeline.

Architecture:
    Main agent calls solve_captcha(screenshot_path, click_fn, vision_fn)
    and gets back a list of pixel coordinates to click.

    Internally, three lightweight "sub-agents" run in sequence:

    Pass 1 — LOCATE:  Coarse chess grid on full page → vision model identifies
             the CAPTCHA widget bounding box → crop coordinates.

    Pass 2 — DETECT:  Pure computer vision (no LLM) on the cropped region.
             Intensity-gradient profiling detects the actual tile grid lines
             (works for Google reCAPTCHA 3×3, 4×4, etc.).

    Pass 3 — CLASSIFY: Re-label the image using detected tile boundaries
             (so each label = exactly one clickable tile) → vision model
             says which tiles contain the target object.

Each sub-agent is a plain function: image in → structured data out.
No memory, no conversation history, minimal prompts.
"""

import json
import logging
import re

from macgent.actions.vision import (
    annotate_image_rowcol,
    detect_tile_grid,
    label_detected_tiles,
    enhance_for_vision,
    image_to_base64,
    _parse_chess_cells_from_text,
)

logger = logging.getLogger("macgent.captcha_solver")

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ── Types ────────────────────────────────────────────────────────────────────

class CaptchaResult:
    """Result of the CAPTCHA solving pipeline."""
    __slots__ = ("captcha_type", "clicks", "drag", "description", "solved")

    def __init__(self):
        self.captcha_type: str = ""       # checkbox, image_grid, slider, text
        self.clicks: list[tuple[int, int]] = []  # (x, y) in full-page coords
        self.drag: tuple | None = None     # (x0, y0, x1, y1) or None
        self.description: str = ""
        self.solved: bool = False

    def __repr__(self):
        return (f"CaptchaResult(type={self.captcha_type!r}, "
                f"clicks={self.clicks}, drag={self.drag}, solved={self.solved})")


# ── Sub-agent 1: LOCATE ─────────────────────────────────────────────────────

LOCATE_PROMPT = """Grid screenshot (A1=top-left, rows A-{last_row}, cols 1-{last_col}).
Find the CAPTCHA. Reply ONLY JSON:
{{"type":"checkbox"|"image_grid"|"slider"|"text","description":"brief","top_left_cell":"B4","bottom_right_cell":"F8"}}
For image_grid: box around the PICTURE TILES only (not header/button)."""


def locate_captcha(screenshot_path: str, vision_fn, cell_size: int = 120):
    """Pass 1: Locate the CAPTCHA widget on a full-page screenshot.

    Args:
        screenshot_path: path to the raw screenshot PNG.
        vision_fn: callable(image_b64: str, prompt: str) → str (model response).
        cell_size: coarse grid cell size in pixels.

    Returns:
        (captcha_type, crop_box, description)
        crop_box = (x0, y0, x1, y1) in full-page pixel coordinates.
        Returns ("none", None, "") if no CAPTCHA found.
    """
    import math
    from PIL import Image

    img = Image.open(screenshot_path)
    iw, ih = img.size

    cols = math.ceil(iw / cell_size)
    rows = math.ceil(ih / cell_size)
    cell_w = iw / cols
    cell_h = ih / rows

    last_row = LETTERS[rows - 1] if rows <= 26 else f"{LETTERS[(rows-1) // 26 - 1]}{LETTERS[(rows-1) % 26]}"
    last_col = cols

    # Generate coarse grid
    annotated, cell_centers, _, _ = annotate_image_rowcol(img, cell_size=cell_size)
    b64 = image_to_base64(annotated)

    prompt = LOCATE_PROMPT.format(last_row=last_row, last_col=last_col)
    response = vision_fn(b64, prompt)
    logger.info(f"[locate] response: {response[:300]}")

    parsed = _parse_json(response)
    captcha_type = parsed.get("type", "none")
    if captcha_type == "none":
        return "none", None, ""

    description = parsed.get("description", "")
    tl = parsed.get("top_left_cell", "A1")
    br = parsed.get("bottom_right_cell", f"{last_row}{last_col}")

    # Convert cell labels to pixel crop box
    tl_parsed = _parse_chess_cells_from_text(tl)
    br_parsed = _parse_chess_cells_from_text(br)
    if not tl_parsed or not br_parsed:
        return captcha_type, (0, 0, iw, ih), description

    r0, c0 = tl_parsed[0]
    r1, c1 = br_parsed[0]

    # Cell centers → crop box with half-cell padding
    cx0 = (c0 + 0.5) * cell_w
    cy0 = (r0 + 0.5) * cell_h
    cx1 = (c1 + 0.5) * cell_w
    cy1 = (r1 + 0.5) * cell_h

    pad_x = cell_w * 0.5
    pad_y = cell_h * 0.5
    crop = (
        max(0, int(cx0 - pad_x)),
        max(0, int(cy0 - pad_y)),
        min(iw, int(cx1 + pad_x)),
        min(ih, int(cy1 + pad_y)),
    )

    logger.info(f"[locate] type={captcha_type}, crop={crop}, desc={description}")
    return captcha_type, crop, description


# ── Sub-agent 2: DETECT TILES ───────────────────────────────────────────────

def detect_captcha_tiles(screenshot_path: str, crop_box: tuple[int, int, int, int],
                         debug_path: str | None = None):
    """Pass 2: Detect the actual tile grid within the cropped CAPTCHA region.

    Pure computer vision — no LLM call.

    Args:
        screenshot_path: path to the raw screenshot.
        crop_box: (x0, y0, x1, y1) from Pass 1.
        debug_path: optional path to save the annotated debug image.

    Returns:
        (tiles, grid_shape, tile_centers, crop_origin)
        tiles: list of (x0, y0, x1, y1) in cropped-image coordinates.
        grid_shape: (n_rows, n_cols).
        tile_centers: tile_centers[r][c] = (cx, cy) in FULL-PAGE coordinates.
        crop_origin: (x0, y0) offset to add to cropped coords for full-page.
    """
    from PIL import Image

    img = Image.open(screenshot_path)
    cx0, cy0, cx1, cy1 = crop_box
    cropped = img.crop(crop_box)

    tiles, grid_shape, div_x, div_y = detect_tile_grid(cropped)

    if not tiles:
        logger.warning("[detect] no tile grid found in crop region")
        return [], (0, 0), [], (cx0, cy0)

    # Label the detected tiles and get centers
    annotated, tile_centers_local = label_detected_tiles(cropped, tiles, grid_shape)

    if debug_path:
        annotated.save(debug_path)
        logger.info(f"[detect] debug image saved: {debug_path}")

    # Shift tile centers to full-page coordinates
    tile_centers = []
    for row in tile_centers_local:
        tile_centers.append([(x + cx0, y + cy0) for x, y in row])

    logger.info(f"[detect] found {grid_shape[0]}×{grid_shape[1]} tile grid")
    return tiles, grid_shape, tile_centers, (cx0, cy0)


# ── Sub-agent 3: CLASSIFY TILES ─────────────────────────────────────────────

CLASSIFY_PROMPT = """You are helping a vision-impaired person solve a CAPTCHA.

This image shows a {n_rows}×{n_cols} grid of picture tiles from a CAPTCHA.
Each tile is labelled with a chess-style code (A1 = top-left).
Rows: A–{last_row} (top to bottom). Columns: 1–{last_col} (left to right).

The CAPTCHA asks: "{description}"

Which tiles contain ANY part of the target object? Include tiles where the object is partially visible (even just an edge or corner). The CAPTCHA expects you to select ALL tiles that overlap with the target.

Reply ONLY with JSON:
{{
  "target": "what you're looking for",
  "tiles": ["A1", "B2", ...]
}}
"""


def classify_tiles(screenshot_path: str, crop_box: tuple[int, int, int, int],
                   tiles: list[tuple[int, int, int, int]],
                   grid_shape: tuple[int, int],
                   description: str, vision_fn) -> list[tuple[int, int]]:
    """Pass 3: Ask vision model which tiles contain the target object.

    Args:
        screenshot_path: path to raw screenshot.
        crop_box: (x0, y0, x1, y1) from Pass 1.
        tiles: tile bounding boxes from Pass 2.
        grid_shape: (n_rows, n_cols) from Pass 2.
        description: CAPTCHA description from Pass 1 (e.g. "Select all stop signs").
        vision_fn: callable(image_b64, prompt) → str.

    Returns:
        List of (row_idx, col_idx) 0-indexed for tiles to click.
    """
    from PIL import Image

    img = Image.open(screenshot_path)
    cropped = img.crop(crop_box)

    # Label with detected tile boundaries — keep COLOR for classification
    # (red stop signs, yellow taxis etc. are invisible in greyscale)
    annotated, _ = label_detected_tiles(cropped, tiles, grid_shape, grayscale=False)
    b64 = image_to_base64(annotated)

    n_rows, n_cols = grid_shape
    last_row = LETTERS[n_rows - 1] if n_rows <= 26 else "Z"
    last_col = n_cols

    prompt = CLASSIFY_PROMPT.format(
        n_rows=n_rows, n_cols=n_cols,
        last_row=last_row, last_col=last_col,
        description=description,
    )

    response = vision_fn(b64, prompt)
    logger.info(f"[classify] response: {response[:300]}")

    parsed = _parse_json(response)
    tile_labels = parsed.get("tiles", [])

    # Parse labels to (row, col) indices
    indices = _parse_chess_cells_from_text(" ".join(tile_labels)) if tile_labels else []
    if not indices:
        # Fallback: parse from raw response
        indices = _parse_chess_cells_from_text(response)

    # Filter to valid tile indices
    indices = [(r, c) for r, c in indices if 0 <= r < n_rows and 0 <= c < n_cols]

    logger.info(f"[classify] tiles to click: "
                f"{[LETTERS[r]+str(c+1) for r,c in indices]}")
    return indices


# ── Main pipeline ────────────────────────────────────────────────────────────

def solve_image_grid_captcha(screenshot_path: str, vision_fn,
                             debug_dir: str = "/tmp") -> CaptchaResult:
    """Full 3-pass pipeline to solve an image-grid CAPTCHA.

    Args:
        screenshot_path: path to a full-page screenshot PNG.
        vision_fn: callable(image_b64: str, prompt: str) → str.
        debug_dir: directory to save debug images.

    Returns:
        CaptchaResult with click coordinates in full-page pixels.
    """
    result = CaptchaResult()

    # Pass 1: Locate
    logger.info("=== Pass 1: LOCATE ===")
    captcha_type, crop_box, description = locate_captcha(
        screenshot_path, vision_fn, cell_size=120
    )
    result.captcha_type = captcha_type
    result.description = description

    if captcha_type == "none" or crop_box is None:
        logger.warning("No CAPTCHA found on page")
        return result

    # For checkbox type, we don't need tile detection
    if captcha_type == "checkbox":
        cx = (crop_box[0] + crop_box[2]) // 2
        cy = (crop_box[1] + crop_box[3]) // 2
        result.clicks = [(cx, cy)]
        result.solved = True
        return result

    if captcha_type != "image_grid":
        logger.info(f"CAPTCHA type '{captcha_type}' — not an image grid, "
                    "returning crop center as best guess")
        cx = (crop_box[0] + crop_box[2]) // 2
        cy = (crop_box[1] + crop_box[3]) // 2
        result.clicks = [(cx, cy)]
        return result

    # Pass 2: Detect tile grid
    logger.info("=== Pass 2: DETECT TILES ===")
    debug_path = f"{debug_dir}/captcha_detected_tiles.png" if debug_dir else None
    tiles, grid_shape, tile_centers, crop_origin = detect_captcha_tiles(
        screenshot_path, crop_box, debug_path=debug_path
    )

    if not tiles:
        logger.warning("Could not detect tile grid — falling back to chess grid")
        # Fallback: use arbitrary chess grid on cropped region
        return _fallback_chess_grid(screenshot_path, crop_box, description,
                                    vision_fn, debug_dir)

    # Pass 3: Classify tiles
    logger.info("=== Pass 3: CLASSIFY ===")
    target_indices = classify_tiles(
        screenshot_path, crop_box, tiles, grid_shape, description, vision_fn
    )

    if not target_indices:
        logger.warning("Vision model found no target tiles")
        return result

    # Convert to full-page click coordinates
    raw_clicks = []
    for r, c in target_indices:
        cx, cy = tile_centers[r][c]
        raw_clicks.append((cx, cy))

    # Deduplicate: if our detected grid is finer than the actual CAPTCHA grid,
    # multiple cells may map to the same real tile. Clicking a tile twice
    # toggles it off.
    # Strategy: find the dominant divider spacing (= real tile size), then
    # snap each click to the nearest real tile center. Only click once per tile.
    from macgent.actions.vision import detect_tile_grid as _dtg
    from PIL import Image as _Image
    _crop_img = _Image.open(screenshot_path).crop(crop_box)
    _, _real_shape, _rdx, _rdy = _dtg(_crop_img, min_tiles=3, max_tiles=4)
    crop_ox, crop_oy = crop_box[0], crop_box[1]

    if _rdx and _rdy:
        # Use detected dividers to snap clicks to real tile centers
        # Build real tile edges (in full-page coords)
        _rdx_fp = [d + crop_ox for d in _rdx]
        _rdy_fp = [d + crop_oy for d in _rdy]

        # Compute dominant spacing for edge estimation
        x_spacings = [_rdx[i+1] - _rdx[i] for i in range(len(_rdx)-1)]
        y_spacings = [_rdy[i+1] - _rdy[i] for i in range(len(_rdy)-1)]
        avg_x_sp = sum(x_spacings) / len(x_spacings) if x_spacings else 100
        avg_y_sp = sum(y_spacings) / len(y_spacings) if y_spacings else 100

        x_edges = [max(crop_ox, int(_rdx_fp[0] - avg_x_sp))] + _rdx_fp + \
                  [min(crop_box[2], int(_rdx_fp[-1] + avg_x_sp))]
        y_edges = [max(crop_oy, int(_rdy_fp[0] - avg_y_sp))] + _rdy_fp + \
                  [min(crop_box[3], int(_rdy_fp[-1] + avg_y_sp))]

        def _snap_to_tile(x, y):
            """Find which real tile (ri, ci) this click falls in."""
            ci = 0
            for i in range(len(x_edges) - 1):
                if x_edges[i] <= x < x_edges[i + 1]:
                    ci = i
                    break
            ri = 0
            for i in range(len(y_edges) - 1):
                if y_edges[i] <= y < y_edges[i + 1]:
                    ri = i
                    break
            # Return tile center
            cx = (x_edges[ci] + x_edges[min(ci + 1, len(x_edges) - 1)]) // 2
            cy = (y_edges[ri] + y_edges[min(ri + 1, len(y_edges) - 1)]) // 2
            return (ri, ci), (cx, cy)

        seen_tiles = set()
        result.clicks = []
        for x, y in raw_clicks:
            tile_id, (cx, cy) = _snap_to_tile(x, y)
            if tile_id not in seen_tiles:
                seen_tiles.add(tile_id)
                result.clicks.append((cx, cy))
                logger.info(f"  tile {tile_id} → click ({cx}, {cy})")

        if len(result.clicks) < len(raw_clicks):
            logger.info(f"[solve] snapped {len(raw_clicks)} → {len(result.clicks)} unique tiles")
    else:
        # Fallback: simple distance-based dedup
        min_dist = min(crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]) / 6
        result.clicks = _deduplicate_clicks(raw_clicks, min_dist)

    result.solved = True
    logger.info(f"[solve] {len(result.clicks)} clicks: {result.clicks}")
    return result


def _fallback_chess_grid(screenshot_path: str, crop_box, description: str,
                         vision_fn, debug_dir: str) -> CaptchaResult:
    """Fallback when tile detection fails: use arbitrary 60px chess grid."""
    from PIL import Image

    result = CaptchaResult()
    result.captcha_type = "image_grid"
    result.description = description

    img = Image.open(screenshot_path)
    cropped = img.crop(crop_box)
    cx0, cy0 = crop_box[0], crop_box[1]

    annotated, cell_centers, rows, cols = annotate_image_rowcol(
        cropped, cell_size=60, grayscale=True
    )
    b64 = image_to_base64(annotated)

    last_row = LETTERS[rows - 1] if rows <= 26 else "Z"
    prompt = CLASSIFY_PROMPT.format(
        n_rows=rows, n_cols=cols,
        last_row=last_row, last_col=cols,
        description=description,
    )

    response = vision_fn(b64, prompt)
    parsed = _parse_json(response)
    labels = parsed.get("tiles", [])
    indices = _parse_chess_cells_from_text(" ".join(labels)) if labels else []
    if not indices:
        indices = _parse_chess_cells_from_text(response)

    indices = [(r, c) for r, c in indices if 0 <= r < rows and 0 <= c < cols]
    for r, c in indices:
        x, y = cell_centers[r][c]
        result.clicks.append((x + cx0, y + cy0))

    result.solved = bool(result.clicks)
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    """Extract first JSON object from model response text."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _deduplicate_clicks(clicks: list[tuple[int, int]],
                        min_dist: float) -> list[tuple[int, int]]:
    """Merge clicks that are within min_dist pixels of each other.

    When our detected grid is finer than the actual CAPTCHA grid, multiple
    cells may map to the same real clickable tile. Clicking the same tile
    twice toggles it off — so we deduplicate by merging nearby clicks into
    their centroid.

    Returns a list of unique click coordinates.
    """
    if not clicks:
        return []

    # Group clicks into clusters where all members are within min_dist
    clusters: list[list[tuple[int, int]]] = []
    used = [False] * len(clicks)

    for i in range(len(clicks)):
        if used[i]:
            continue
        cluster = [clicks[i]]
        used[i] = True
        for j in range(i + 1, len(clicks)):
            if used[j]:
                continue
            # Check distance to any member of the cluster
            x2, y2 = clicks[j]
            for cx, cy in cluster:
                dist = ((x2 - cx) ** 2 + (y2 - cy) ** 2) ** 0.5
                if dist < min_dist:
                    cluster.append(clicks[j])
                    used[j] = True
                    break
        clusters.append(cluster)

    # Centroid of each cluster
    result = []
    for cluster in clusters:
        cx = sum(x for x, y in cluster) // len(cluster)
        cy = sum(y for x, y in cluster) // len(cluster)
        result.append((cx, cy))

    return result
