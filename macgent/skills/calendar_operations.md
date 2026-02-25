# Calendar Operations Skill

Read calendar events, check availability, and understand meeting schedules.

## Actions

### read_calendar
Read upcoming calendar events.

```
Action: read_calendar
Params: {"days_ahead": 7}
```

Returns:
- Event title
- Start time and date
- End time
- Duration
- Location (if specified)
- Attendees (if available)

Parameters:
- `days_ahead` - Number of days to look ahead (default: 7)

### check_availability
Check if a time slot is available.

```
Action: check_availability
Params: {
    "date": "2026-03-15",
    "start_time": "14:00",
    "end_time": "15:00",
    "duration_minutes": 60
}
```

Returns:
- Available: true/false
- Conflicting events (if any)
- Time suggestions (if time slot unavailable)

### get_calendar_summary
Get a summary of calendar for a specific date or range.

```
Action: get_calendar_summary
Params: {
    "date": "2026-03-15"
}
```

Returns:
- Total events for that day
- Free time blocks
- Calendar view summary

## Common Patterns

### Check Tomorrow's Schedule
1. `read_calendar` with days_ahead=1
2. Extract event times and titles
3. Identify free time
4. Report summary

### Find Free Time for Meeting
1. `check_availability` for desired time slot
2. If not available, request alternative times
3. Return available options

### Understand Meeting Duration
When reading an email with meeting invite:
1. Extract suggested time from email
2. `check_availability` for that time
3. If conflict, find alternate times
4. Report availability

## Tips & Gotchas

- **Calendar must be configured** - Calendar app must have access to your calendars
- **Multiple calendars** - May show events from all configured calendars
- **All-day events** - Returned separately; don't block specific times
- **Busy blocks** - Busy/free status from Outlook/Exchange calendars is respected
- **Time zone aware** - Times are in your system time zone
- **No event creation** - Can read but not create/modify events (yet)

## Related Skills

- [Email Operations](./email_operations.md) - Handle calendar invites in emails
