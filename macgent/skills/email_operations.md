# Skill: Email Operations

## Type
Core

## Purpose
Operate the macOS Mail inbox directly for reading, sending, and replying to email.

## Actions / Usage

```json
{"type": "mail_read", "params": {"limit": 5}}
{"type": "mail_read_full", "params": {"number": 1}}
{"type": "mail_send", "params": {"to": "recipient@example.com", "subject": "Subject", "body": "Body"}}
{"type": "mail_reply", "params": {"number": 1, "body": "Thanks"}}
```

## Constraints

- This skill maps to `mail_*` actions only.
- Do not use deprecated names like `read_email` or `send_email` in action JSON.
- Prefer concise, explicit subjects and message bodies.

## Examples

1. Read latest 5 inbox messages and summarize action items.
2. Reply to message #1 with requested update.
3. Send a status email to a recipient.

## Failure / Escalation

If message index is invalid or Mail account is unavailable, return a clear failure reason.
