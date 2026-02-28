# Skill: Telegram

Send messages to the CEO (your human) via Telegram.

## send_telegram

```json
{"type": "send_telegram", "params": {"text": "Your message here"}}
```

- Sends to the pre-configured chat ID — no `chat_id` param needed.
- Supports Markdown formatting (bold, italic, code, links).
- Keep messages concise and human-friendly.

## When to use

- Reporting task completion or results
- Asking the CEO a question or for clarification
- Alerting about a blocked task
- Sending the bootstrap introduction

## When NOT to use

- Empty heartbeats with nothing actionable — respond `HEARTBEAT_OK` instead.
- Spamming routine status ("I started task X", "I am doing Y") — only message when you need human input or have a result.
