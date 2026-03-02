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

## CAPTCHA Handling

Use the simplest method that works. Do not force the grid solver for every CAPTCHA. Browser-agent is able to take screenshots; very rarely captchas can be solved without vision and coordinates; thus, you should solve them by using screenshots and extracting coordinates with vision tools. 

### Available CAPTCHA / Vision Tools

| File | Capability |
|------|------------|
| `macgent/actions/captcha_solver.py` | `solve_image_grid_captcha(screenshot_path, vision_fn)` for image-grid CAPTCHAs. Returns ordered click coordinates. |
| `macgent/actions/vision.py` | `call_vision(image, prompt, ...)` generic multimodal call (image + prompt), plus helpers like `annotate_image_rowcol()`, `detect_tile_grid()`, `label_detected_tiles()`, `image_to_base64()`. |
| `workspace/scripts/solve_captcha_grid.py` | Runnable end-to-end reference flow. |

### Decision Guide

1. **Simple "Click here / I am human" button or checkbox visible on screen**
Use normal browser clicks directly. Optionally take one screenshot and call `call_vision(...)` to locate the element first.

2. **Image-grid CAPTCHA ("select all buses", "traffic lights", etc.)**
Use `solve_image_grid_captcha(...)`. It returns `result.clicks` as full-page `(x, y)` coordinates in the sequence to click, which then can be directly fed into `click(...)` without needing to identify the underlying element selectors.

3. **Text CAPTCHA / distorted letters / simple visual question**
Take screenshot, call `call_vision(...)` with a strict prompt (for example: "return only the text"), then type and submit.

4. **Unclear layout**
Use `annotate_image_rowcol(...)` and ask `call_vision(...)` for cell labels or absolute coordinates, then click/type manually.

### Grid Solver (What It Returns)

`solve_image_grid_captcha(...)` output:

- `captcha_type`: `checkbox` | `image_grid` | `slider` | `text` | `none`
- `clicks`: ordered list like `[(x1, y1), (x2, y2), ...]`
- `solved`: boolean
- `description`: parsed CAPTCHA instruction text

For `image_grid`, click every coordinate in `result.clicks` in order, then click Verify/Submit.
