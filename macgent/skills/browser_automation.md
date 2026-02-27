# Skill: Browser Automation

## Type
Core

## Purpose
Safari action loop for direct browser control. In `hybrid` mode this is attempted first, then falls back to `browser_task` when stuck/errors/captcha are detected.

## Actions / Usage

- `navigate` `{ "url": "https://..." }`
- `click` `{ "index": 5 }` or `{ "text": "Search" }`
- `type` `{ "index": 3, "text": "query" }`
- `key_press` `{ "key": "return" }`
- `scroll` `{ "direction": "down", "amount": 500 }`
- `execute_js` `{ "code": "document.title" }`
- `wait` `{ "seconds": 2 }`

## Constraints

- Prefer element indexes over text selectors.
- Dismiss popups before normal interactions.
- In `hybrid` mode, repeated stuck actions or challenge signals trigger automatic delegation to `browser_task`.

## Examples

1. Navigate -> type query -> press return -> extract text.
2. Click indexed form fields and submit.

## Failure / Escalation

If Safari loop keeps failing or challenge pages are detected, delegate to `browser_task`.
