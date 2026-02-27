# Skill: Evaluate Image

## Type
Core

## Purpose
Provide a reliable image-understanding fallback for text-only models by routing image analysis to the configured vision model chain.

## Actions / Usage

```json
{"type": "evaluate_image", "params": {"path": "workspace/screenshots/page.png", "prompt": "Describe key UI elements and blockers"}}
```

Or with inline image:

```json
{"type": "evaluate_image", "params": {"image_base64": "...", "media_type": "image/png", "prompt": "Extract text and summarize"}}
```

Optional params:
- `max_tokens` (default: 800)
- `media_type` (default: `image/png`)

## Constraints

- Requires at least one configured vision offer with valid API key.
- If `path` is relative, it is resolved from workspace root.

## Failure / Escalation

Returns a clear error when image input is missing, file is not found, or all vision offers fail.
