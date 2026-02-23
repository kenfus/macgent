# Skill: macOS Direct Actions

These actions call macOS apps via AppleScript — **no browser navigation needed**.

## Mail

```json
{"type": "mail_read", "params": {"limit": 5}}
{"type": "mail_read_full", "params": {"number": 1}}
{"type": "mail_send", "params": {"to": "user@example.com", "subject": "Hello", "body": "Message"}}
{"type": "mail_reply", "params": {"number": 1, "body": "Reply text"}}
```

**NEVER navigate to Gmail or any website. Just call `mail_read` / `mail_send` directly.**

## Calendar

```json
{"type": "calendar_read", "params": {"year": 2026, "month": 3, "day": 15}}
{"type": "calendar_add", "params": {"summary": "Meeting", "year": 2026, "month": 3, "day": 15, "hour": 14, "minute": 0, "duration_hours": 1}}
```

**NEVER open the Calendar app or navigate anywhere. Just call the action.**

## iMessage

```json
{"type": "imessage_read", "params": {"contact": "+41791234567", "limit": 10}}
{"type": "imessage_send", "params": {"contact": "+41791234567", "text": "Hello!"}}
```

**NEVER open Messages app or navigate anywhere. Just call the action.**

## Key Rule

If the task involves email, calendar, or iMessage:
→ Use the direct action **immediately**
→ Do NOT `navigate`, do NOT `open_app` first
→ The first action should be the macOS action itself
