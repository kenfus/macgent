import logging
from macgent.perception.safari import run_osascript

logger = logging.getLogger("macgent.actions.calendar")

# Auto-detect default calendar on first use
_default_calendar = None


def _get_default_calendar() -> str:
    """Get the first writable calendar name."""
    global _default_calendar
    if _default_calendar:
        return _default_calendar
    cals = list_calendars()
    # Pick first non-system calendar
    system_cals = {"Birthdays", "Siri Suggestions", "Scheduled Reminders"}
    for name in cals.split(", "):
        name = name.strip()
        if name and name not in system_cals and "Feiertage" not in name:
            _default_calendar = name
            return name
    return cals.split(", ")[0].strip()


def add_event(summary: str, year: int, month: int, day: int,
              hour: int = 12, minute: int = 0,
              duration_hours: int = 1,
              calendar_name: str | None = None) -> str:
    """Add an event to macOS Calendar using numeric date parts (locale-safe).

    Args:
        summary: Event title
        year, month, day: Date components
        hour, minute: Start time (24h format)
        duration_hours: Event duration in hours
        calendar_name: Calendar to use (auto-detected if None)
    """
    if not calendar_name:
        calendar_name = _get_default_calendar()

    escaped_summary = summary.replace('"', '\\"')
    escaped_cal = calendar_name.replace('"', '\\"')

    # Build date programmatically in AppleScript (locale-independent)
    script = f'''
    tell application "Calendar"
        set startDate to current date
        set year of startDate to {year}
        set month of startDate to {month}
        set day of startDate to {day}
        set hours of startDate to {hour}
        set minutes of startDate to {minute}
        set seconds of startDate to 0

        set endDate to startDate + ({duration_hours} * 60 * 60)

        tell calendar "{escaped_cal}"
            make new event with properties {{summary:"{escaped_summary}", start date:startDate, end date:endDate}}
        end tell
        activate
    end tell
    '''
    run_osascript(script)
    return f"Added calendar event: '{summary}' on {year}-{month:02d}-{day:02d} at {hour:02d}:{minute:02d} to calendar '{calendar_name}'"


def list_calendars() -> str:
    """List available calendar names."""
    script = '''
    tell application "Calendar"
        set calNames to name of every calendar
        set output to ""
        repeat with n in calNames
            set output to output & n & ", "
        end repeat
        return output
    end tell
    '''
    return run_osascript(script)


def open_calendar() -> str:
    """Open the Calendar app."""
    run_osascript('tell application "Calendar" to activate')
    return "Opened Calendar app"
