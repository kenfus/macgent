import logging
from macgent.perception.safari import run_osascript

logger = logging.getLogger("macgent.actions.calendar")

_default_calendar = None


def _get_default_calendar() -> str:
    """Get the first writable calendar name."""
    global _default_calendar
    if _default_calendar:
        return _default_calendar
    cals = list_calendars()
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
    """Add an event to macOS Calendar."""
    if not calendar_name:
        calendar_name = _get_default_calendar()

    escaped_summary = summary.replace('"', '\\"')
    escaped_cal = calendar_name.replace('"', '\\"')

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
    return f"Added event: '{summary}' on {year}-{month:02d}-{day:02d} at {hour:02d}:{minute:02d}"


def read_events(year: int, month: int, day: int) -> str:
    """Read all calendar events for a specific date."""
    script = f'''
    tell application "Calendar"
        set startDate to current date
        set year of startDate to {year}
        set month of startDate to {month}
        set day of startDate to {day}
        set hours of startDate to 0
        set minutes of startDate to 0
        set seconds of startDate to 0

        set endDate to startDate + (24 * 60 * 60)

        set output to ""
        repeat with cal in calendars
            set calName to name of cal
            try
                set dayEvents to (every event of cal whose start date >= startDate and start date < endDate)
                repeat with ev in dayEvents
                    set evStart to start date of ev
                    set h to hours of evStart
                    set m to minutes of evStart
                    set timeStr to (h as text) & ":" & (text -2 thru -1 of ("0" & (m as text)))
                    set output to output & timeStr & " - " & summary of ev & " [" & calName & "]" & linefeed
                end repeat
            end try
        end repeat

        if output is "" then
            return "No events on {year}-{month:02d}-{day:02d}"
        else
            return output
        end if
    end tell
    '''
    return run_osascript(script, timeout=15)


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
