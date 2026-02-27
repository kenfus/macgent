# Skill: macOS Direct Actions

## Type
Core

## Purpose
Always-available native macOS control for Mail, Calendar, and Messages. These actions do not require browser navigation.

## Actions / Usage

### Mail

```json
{"type": "mail_read", "params": {"limit": 5}}
{"type": "mail_read_full", "params": {"number": 1}}
{"type": "mail_send", "params": {"to": "user@example.com", "subject": "Hello", "body": "Message"}}
{"type": "mail_reply", "params": {"number": 1, "body": "Reply text"}}
```

### Calendar

```json
{"type": "calendar_read", "params": {"year": 2026, "month": 3, "day": 15}}
{"type": "calendar_add", "params": {"summary": "Meeting", "year": 2026, "month": 3, "day": 15, "hour": 14, "minute": 0, "duration_hours": 1}}
```

### iMessage

```json
{"type": "imessage_read", "params": {"contact": "+41791234567", "limit": 10}}
{"type": "imessage_send", "params": {"contact": "+41791234567", "text": "Hello!"}}
```

## Constraints

- Do not route Mail/Calendar/Messages tasks through web UI unless explicitly requested.
- Call direct actions immediately; avoid opening browser tabs for these operations.

## Failure / Escalation

If native app control fails, return a clear error and required manual preconditions (app permissions/account setup).
