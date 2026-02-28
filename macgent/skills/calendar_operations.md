# Skill: Calendar

Read calendar events and check availability via macOS Calendar app.

## Actions

```json
{"type": "calendar_read",         "params": {"year": 2026, "month": 3, "day": 15}}
{"type": "calendar_add",          "params": {"summary": "Meeting", "year": 2026, "month": 3, "day": 15, "hour": 14, "minute": 0, "duration_hours": 1}}
{"type": "check_availability",    "params": {"date": "2026-03-15", "start_time": "14:00", "end_time": "15:00"}}
{"type": "get_calendar_summary",  "params": {"date": "2026-03-15"}}
```

- Times are in the system time zone
- All-day events don't block specific time slots
- Calendar app must have access to your calendars
