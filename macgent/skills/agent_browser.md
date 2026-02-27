# Skill: Agent Browser

## Type
Core

## Purpose
Primary browser automation runtime for web tasks. Use this via `browser_task` when robust, open-source browser control is needed.

## Actions / Usage

### Primary action

```json
{"type": "browser_task", "params": {"task": "Open https://example.com and summarize the page"}}
```

Optional parameters:

```json
{"type": "browser_task", "params": {"task": "...", "mode": "agent_browser", "max_steps": 30, "capture_artifacts": true}}
```

Response contract (JSON string):
- `backend` (always `agent_browser`)
- `attempts` (int)
- `solved` (bool)
- `blocked_reason` (string or null)
- `artifact_dir` (path or null)

## Constraints

- Use `browser_task` for browser-heavy tasks by default.
- For captcha/anti-bot pages, a single auto-attempt is allowed; unresolved flows must escalate as blocked.
- Do not claim success when `solved=false`.

## Examples

- Search and summarize results page
- Open a listing website and collect key fields
- Continue work on dynamic SPA pages when Safari loop is stuck

## Failure / Escalation

If `blocked_reason` is set, report blockage and include the artifact path for debugging.
