# Skill: macOS Control

Control any macOS app — or a mirrored iPhone — using typed actions for mouse, keyboard, screen, and AppleScript.

---

## Actions Reference

### Mouse
```json
{"type": "mouse_click",        "params": {"x": 452, "y": 310}}
{"type": "mouse_double_click", "params": {"x": 452, "y": 310}}
{"type": "mouse_move",         "params": {"x": 452, "y": 310}}
```

### Keyboard
```json
{"type": "key_press",   "params": {"key": "return"}}
{"type": "type_string", "params": {"text": "Hello World"}}
```
Simple keys: `return`, `escape`, `tab`, `space`, `arrow-left`, `arrow-right`, `arrow-up`, `arrow-down`, `f1`–`f12`

For key combos (cmd+c, cmd+v, etc.) use `applescript` — see below.

### Screenshot + Vision
```json
{"type": "screenshot",     "params": {"path": "screenshots/ui.png"}}
{"type": "evaluate_image", "params": {"path": "screenshots/ui.png", "prompt": "Where is the Submit button? Give pixel offset from top-left."}}
```
`path` is relative to workspace. Omit to auto-name by timestamp.

### locate_in_app — find an element and get its absolute coordinates (preferred)
One-shot: gets window bounds, takes a gridded screenshot, asks the vision model, returns `{"x": N, "y": N}` ready for `mouse_click`. Use this instead of manual screenshots when you need to click something.
```json
{"type": "locate_in_app", "params": {"app": "iPhone Mirroring", "query": "Roman Studer chat row center"}}
{"type": "locate_in_app", "params": {"app": "Spotify", "query": "Play button", "grid_step": 30}}
```
- `app` — exact process name (same as used in System Events)
- `query` — plain-English description of the element to find
- `grid_step` — grid density in logical pixels (default 50; use 25–30 for dense UIs)

Returns `{"x": 1274, "y": 967, "screenshot": "screenshots/locate_....png"}` — pass `x`/`y` directly to `mouse_click`.

### screenshot_grid — coordinate overlay (use when you need exact click position)
Takes a screenshot of a region and burns an **absolute screen coordinate grid** onto it. Read the coordinate labels directly from the image — no guessing or converting required.
```json
{"type": "screenshot_grid", "params": {"x": 1124, "y": 348, "w": 312, "h": 694}}
{"type": "screenshot_grid", "params": {"x": 1124, "y": 348, "w": 312, "h": 694, "grid_step": 30, "path": "screenshots/grid.png"}}
```
- `x, y, w, h` — region in absolute screen coordinates (use window bounds from `applescript`)
- `grid_step` — grid spacing in logical pixels (default 50)

Then pass the result to `evaluate_image`:
```json
{"type": "evaluate_image", "params": {"path": "screenshots/grid.png", "prompt": "Read the grid coordinate labels. What are the absolute screen coordinates (x, y) of the center of the message text input field?"}}
```
The vision model reads the burned-in labels and returns the exact coordinate to use in `mouse_click`.

### AppleScript
```json
{"type": "applescript", "params": {"script": "tell application \"Spotify\" to play"}}
```
- `timeout` (optional): seconds before giving up (default 15)

### Open App
```json
{"type": "open_app", "params": {"app": "Finder"}}
```

---

## Visual Interaction Pattern

To click anything on screen — a button, icon, or UI element — follow these four steps:

**1. Activate the app** (bring window to front)
```json
{"type": "open_app", "params": {"app": "Notes"}}
```

**2. Get window position and size**
```json
{"type": "applescript", "params": {"script": "tell application \"System Events\"\n  tell process \"Notes\"\n    set p to position of window 1\n    set s to size of window 1\n    return (item 1 of p) & \",\" & (item 2 of p) & \",\" & (item 1 of s) & \",\" & (item 2 of s)\n  end tell\nend tell"}}
```
Returns `win_x,win_y,width,height` — the window's top-left in absolute screen coordinates.

**3. Screenshot and identify the target**
```json
{"type": "screenshot",     "params": {"path": "screenshots/app.png"}}
{"type": "evaluate_image", "params": {"path": "screenshots/app.png", "prompt": "Find the New Note button. What is its pixel offset (x, y) from the top-left corner of the image?"}}
```
Vision model returns e.g. `offset_x=280, offset_y=42`.

**4. Click at absolute coordinates**
```
absolute_x = win_x + offset_x
absolute_y = win_y + offset_y
```
```json
{"type": "mouse_click", "params": {"x": 1404, "y": 390}}
```

After clicking, take a new screenshot to confirm the result before continuing.

---

## AppleScript Reference

**App control**
```json
{"type": "applescript", "params": {"script": "tell application \"Spotify\" to play track \"spotify:track:...\""}}
{"type": "applescript", "params": {"script": "tell application \"Finder\" to get name of every file in desktop"}}
```

**Key combos** (more reliable than cliclick for modifier keys)
```json
{"type": "applescript", "params": {"script": "tell application \"System Events\" to keystroke \"c\" using command down"}}
{"type": "applescript", "params": {"script": "tell application \"System Events\" to keystroke \"v\" using command down"}}
{"type": "applescript", "params": {"script": "tell application \"System Events\" to key code 36"}}
```

**Click menu items by label** (more reliable than coordinates for menu bars)
```json
{"type": "applescript", "params": {"script": "tell application \"System Events\"\n  tell process \"Finder\"\n    click menu item \"New Folder\" of menu \"File\" of menu bar 1\n  end tell\nend tell"}}
```

**System**
```json
{"type": "applescript", "params": {"script": "set volume output volume 50"}}
{"type": "applescript", "params": {"script": "display notification \"Done!\" with title \"MacGent\""}}
{"type": "applescript", "params": {"script": "get the clipboard"}}
{"type": "applescript", "params": {"script": "set the clipboard to \"some text\""}}
```

---

## iPhone Mirroring

iPhone Mirroring (macOS 15+) is a regular macOS window. Use the same four-step pattern as any other app:

```json
{"type": "open_app", "params": {"app": "iPhone Mirroring"}}
{"type": "applescript", "params": {"script": "tell application \"System Events\"\n  tell process \"iPhone Mirroring\"\n    set p to position of window 1\n    set s to size of window 1\n    return (item 1 of p) & \",\" & (item 2 of p) & \",\" & (item 1 of s) & \",\" & (item 2 of s)\n  end tell\nend tell"}}
{"type": "screenshot",     "params": {"path": "screenshots/iphone.png"}}
{"type": "evaluate_image", "params": {"path": "screenshots/iphone.png", "prompt": "Find the WhatsApp icon. What is its pixel offset from the top-left?"}}
{"type": "mouse_click",    "params": {"x": 1319, "y": 993}}
```

---

## Tips

- **Coordinates are logical points** (not retina pixels). On a 2× Retina display the logical space is half the physical resolution — cliclick and osascript both use logical points automatically.
- **Always activate first** so the window is on top.
- **For text fields**: `mouse_click` to focus, then `type_string`.
- **For menus**: prefer `applescript` `click menu item` over coordinates — labels are stable, positions shift.
- **If a click misses**: re-screenshot, re-evaluate, adjust by the error and retry.
