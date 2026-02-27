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
