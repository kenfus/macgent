# Skill: Telegram

Send messages to the CEO (your human) via Telegram.

## send_telegram

```json
{"type": "send_telegram", "params": {"text": "Your message here"}}
```

- Sends to the pre-configured chat ID — no `chat_id` param needed.
- Supports Markdown formatting (bold, italic, code, links).
- Keep messages concise and human-friendly.

## When NOT to use send_telegram

- Empty heartbeats with nothing actionable — use `{"type": "heartbeat_ok"}` instead.
- Routine status updates the CEO didn't ask for.
- Announcing work you are about to do — just do the work, then report the result.
