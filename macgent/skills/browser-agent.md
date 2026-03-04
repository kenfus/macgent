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
- `click(ref)` — click element by ref from snapshot
- `select(ref, value)` — select an option from a `<select>` dropdown/combobox by display text
- `fill(ref, text)` — clear an input and type into it
- `press(key)` — keyboard action (Enter, Tab, Escape, ArrowDown, Space, etc.)
- `scroll(direction, pixels)` — scroll page up/down/left/right
- `snapshot(interactive=true)` — accessibility tree with inline `[ref=eN]` markers; this is what the LLM reads
- `screenshot(path)` — capture page image and saves to `path`
- `get_text()` / `get_title()` / `get_url()` — read page state

### Ref format

The snapshot returns a hierarchical text tree. Interactive elements have `[ref=eN]` markers:

```
- button "I Accept" [ref=e3]
- combobox "Price to" [ref=e7]
- option "1,250,000 CHF" [ref=e12]
```

To interact, prepend `@`:
```json
{"type": "click", "params": {"ref": "@e3"}}
{"type": "select", "params": {"ref": "@e7", "value": "1,250,000 CHF"}}
```

**Important**: refs are only valid after the most recent `snapshot()` call. Each step in the browser loop takes a fresh snapshot, so refs are always current.

### Overlay / Cookie Handling (critical)

Cookie consent banners, login popups, and "Sign in with Google" overlays **block all other elements** until dismissed. They typically appear at the END of the snapshot (high ref numbers), or in a separate `--- OVERLAY / CONSENT ---` section.

**Always dismiss overlays first**, before attempting any other interaction. Look for:
- "I Accept", "Accept all", "Accept cookies"
- "Decline", "Reject all"
- "Close", "×", dismiss buttons
- "Sign in with Google" → close/dismiss, don't sign in

### Dropdown / Combobox Filters

For `<select>` elements (shown as `combobox` in the snapshot), use the `select` action — NOT `click` on individual options. Options inside `<select>` are not directly clickable.

```json
{"type": "select", "params": {"ref": "@e23", "value": "1,250,000 CHF"}}
```

The value must match the option's display text exactly as shown in the snapshot.

### Interaction Patterns

| Element type | Action | Example |
|---|---|---|
| button, link, checkbox | `click` | `click @e3` |
| combobox / dropdown (`<select>`) | `select` | `select @e7 "4.5"` |
| text input, searchbox | `fill` then `press Enter` | `fill @e14 "Basel"` → `press Enter` |
| overlay / consent banner | `click` the accept/close button | `click @e345` |

## Constraints

- For lookup-only tasks, use `brave_search` first.
- Use `browser_task` when page interaction is required.
- When a site encodes filters in URL params, navigate directly instead of using the filter UI.
- When a site uses React/SPA state for filters (no URL params), use `select` on comboboxes.
- Example: homegate.ch updates the URL after filter selection — `?ac=4.5&aj=1250000` means rooms≥4.5, price≤1.25M.

## Failure / Escalation

If `browser_task` returns `solved=false`, report `blocked_reason` and artifact path.

---

## CAPTCHA / Challenge Handling

**LLM-first, tools as primitives.** The agent should reason about what it sees and use the available tools to solve challenges — not blindly call a pre-coded routine. Before doing anything, verify it is actually a CAPTCHA and not a ban page, rate-limit, or error:

- A real CAPTCHA has an interactive challenge (grid, checkbox, slider, text input).
- A ban/block page typically shows a plain message with no interactive element — `fail` with a clear reason in this case.

### Available Tools

| Tool | What it gives you |
|------|-------------------|
| `screenshot /tmp/cap.png` | Saves current page as image |
| `annotate_image_rowcol(path)` | Draws a chess-label grid (A1, B2...) over the image and returns the annotated path |
| `call_vision(image_path, prompt)` | Sends image + prompt to vision LLM; returns text answer |
| `solve_captcha` (browser action) | Full automated 3-pass pipeline (locate → detect → classify). Use as a shortcut when you don't want to reason manually. |

### How to Reason Through a Challenge

**Simple button or checkbox** ("I Accept", "I am not a robot"):
- Read the snapshot. Find the button/checkbox ref. Click it directly. No vision needed.

**Image-grid tile challenge** ("select all images with traffic lights"):
1. Take a screenshot.
2. Call `annotate_image_rowcol` to overlay a labelled grid on the image.
3. Call `call_vision(annotated_image, "Which labelled cells contain a traffic light? List only the cell labels.")`.
4. Click the cells it names, then click Verify.
5. If the grid refreshes (new images appear), repeat from step 1.
6. Alternatively, call `solve_captcha` to run the full automated pipeline.

**Text / distorted letter CAPTCHA**:
1. Take a screenshot.
2. Call `call_vision(screenshot, "What text is shown in this CAPTCHA? Return only the characters.")`.
3. Fill the text input and submit.

**Unclear / zoomed-in tiles**:
- Crop the image if needed, regrid with `annotate_image_rowcol`, and ask the vision model to zoom in on specific cells before deciding where to click.

### Grid Solver (automated fallback)

`solve_captcha` runs automatically — only use it when you prefer not to reason manually. However, you first need to understand what type of CAPTCHA it is (see below) and then pass the correct params:

- `captcha_type`: `checkbox` | `image_grid` | `slider` | `text` | `none`
- `clicks`: ordered `[(x, y), ...]` coordinates to click in sequence
- `solved`: boolean
