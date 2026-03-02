# Skill: Browser Agent

## Type
Core

## Purpose
Use agent-browser as the default open-source browser runtime.

## Actions / Usage

Primary dispatcher action:

```json
{"type": "browser_task", "params": {"task": "Open https://example.com and inspect it"}}
```

The wrapper expects a URL in `task`.

## Core Browser-Agent Primitives

- `open(url)` — navigate to page
- `click(selector|ref)` — click element
- `type(selector|ref, text)` — input text
- `press(key)` — keyboard action
- `mouse_wheel(dy, dx)` — scroll
- `snapshot(interactive=true)` — list interactable elements
- `screenshot(path)` — capture page image
- `get_text()` / `get_title()` / `get_url()` — read page state

## Constraints

- For lookup-only tasks, use `brave_search` first.
- Use `browser_task` when page interaction is required.

## Failure / Escalation

If `browser_task` returns `solved=false`, report `blocked_reason` and artifact path.

---

## CAPTCHA Solving — 3-Pass Sub-Agent Pipeline

macgent solves easy visual CAPTCHAs using a 3-pass pipeline with lightweight
"sub-agent" vision calls. No DOM queries, no site-specific selectors.


| File | Purpose |
|------|---------|
| `macgent/actions/captcha_solver.py` | 3-pass pipeline: `solve_image_grid_captcha()`, `locate_captcha()`, `detect_captcha_tiles()`, `classify_tiles()` |
| `macgent/actions/vision.py` | Image helpers: `detect_tile_grid()`, `label_detected_tiles()`, `annotate_image_rowcol()`, `image_to_base64()`, `_parse_chess_cells_from_text()` |
| `workspace/scripts/solve_captcha_grid.py` | Standalone test script (run with `uv run python`) |

### Usage

```python
from macgent.actions.captcha_solver import solve_image_grid_captcha

def call_vision(image_b64: str, prompt: str) -> str:
    """Your vision model call — returns model response text."""
    ...

result = solve_image_grid_captcha("/tmp/screenshot.png", call_vision)
# result.captcha_type = "checkbox" | "image_grid" | ...
# result.clicks = [(x1, y1), (x2, y2), ...]  # full-page pixel coords
# result.solved = True/False
```

### Vision Model

| Model | Provider | Key env | max_tokens | Notes |
|-------|----------|---------|-----------|-------|
| `moonshotai/kimi-k2.5:free` | Kilo (`api.kilo.ai`) | `KILO_API_KEY` | 16384 | Reasoning model. Burns most tokens on chain-of-thought, needs generous max_tokens. |

### How the 3 Passes Work

#### Pass 1: LOCATE (coarse grid → bounding box)

- Overlay 120px chess grid (A1-style labels) on full-page screenshot
- Ask kimi: "Find the CAPTCHA, return top_left_cell and bottom_right_cell"
- Convert cell labels → pixel crop box (center-to-center math + half-cell padding)

#### Pass 2: DETECT TILES (pure computer vision, no LLM)

`detect_tile_grid(img)` in vision.py:
- Computes per-row and per-column average brightness profiles
- Finds "peak lines" — narrow bands where brightness differs from local neighbourhood
- Clusters peaks into divider positions
- Picks the best evenly-spaced set of dividers (prefers 3-4 tiles per axis)
- Returns tile bounding boxes and grid shape

Works for both bright dividers (white lines) and dark dividers (gaps).

#### Pass 3: CLASSIFY (color image → tile labels)

- Label the cropped CAPTCHA with detected tile boundaries (1 label = 1 real tile)
- **Keep COLOR** — red stop signs, yellow taxis etc. are invisible in greyscale
- Ask kimi: "Which tiles contain ANY part of the target? Include partial overlaps."
- Parse tile labels → pixel coordinates


### CAPTCHA Types & Strategies

| Type | Strategy |
|------|----------|
| Checkbox | Pass 1 locates it → click center of bounding box |
| Image grid (stop signs, etc.) | Full 3-pass pipeline → click tile centers → Verify button |
| Text/Wiggles | Screenshot → vision model reads distorted text → type into input → Submit |
| Slider/sweep | Coarse grid for start/end → interpolated drag with mouse down/move/up |

