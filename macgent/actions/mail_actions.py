import logging
from macgent.perception.safari import run_osascript

logger = logging.getLogger("macgent.actions.mail")


def read_inbox(limit: int = 5) -> str:
    """Read recent emails from macOS Mail inbox."""
    script = f'''
    tell application "Mail"
        set output to ""
        set msgs to messages of inbox
        set maxMsgs to {limit}
        repeat with i from 1 to (count of msgs)
            if i > maxMsgs then exit repeat
            set msg to item i of msgs
            set subj to subject of msg
            set sndr to sender of msg
            set dt to date received of msg
            set isRead to read status of msg
            set readFlag to "unread"
            if isRead then set readFlag to "read"
            set preview to (extract name from sender of msg)
            set output to output & i & ". [" & readFlag & "] From: " & sndr & linefeed
            set output to output & "   Subject: " & subj & linefeed
            set output to output & "   Date: " & (dt as text) & linefeed & linefeed
        end repeat
        if output is "" then
            return "No emails in inbox."
        end if
        return output
    end tell
    '''
    try:
        return run_osascript(script, timeout=20)
    except Exception as e:
        return f"Could not read mail: {e}"


def read_email(message_number: int = 1) -> str:
    """Read the full content of a specific email by number (1-based)."""
    script = f'''
    tell application "Mail"
        set msg to message {message_number} of inbox
        set subj to subject of msg
        set sndr to sender of msg
        set dt to date received of msg
        set body to content of msg
        -- Truncate body
        if length of body > 2000 then
            set body to text 1 thru 2000 of body & "..."
        end if
        return "From: " & sndr & linefeed & "Subject: " & subj & linefeed & "Date: " & (dt as text) & linefeed & linefeed & body
    end tell
    '''
    try:
        return run_osascript(script, timeout=15)
    except Exception as e:
        return f"Could not read email: {e}"


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email via macOS Mail."""
    escaped_to = to.replace('"', '\\"')
    escaped_subj = subject.replace('"', '\\"')
    escaped_body = body.replace('"', '\\"')

    script = f'''
    tell application "Mail"
        set newMsg to make new outgoing message with properties {{subject:"{escaped_subj}", content:"{escaped_body}", visible:true}}
        tell newMsg
            make new to recipient at end of to recipients with properties {{address:"{escaped_to}"}}
        end tell
        send newMsg
    end tell
    '''
    try:
        run_osascript(script, timeout=15)
        return f"Sent email to {to}: {subject}"
    except Exception as e:
        return f"Failed to send email: {e}"


def reply_email(message_number: int, body: str) -> str:
    """Reply to an email by number (1-based) in inbox."""
    escaped_body = body.replace('"', '\\"')

    script = f'''
    tell application "Mail"
        set msg to message {message_number} of inbox
        set sndr to sender of msg
        set subj to "Re: " & subject of msg

        set newMsg to make new outgoing message with properties {{subject:subj, content:"{escaped_body}", visible:true}}
        tell newMsg
            make new to recipient at end of to recipients with properties {{address:sndr}}
        end tell
        send newMsg
    end tell
    '''
    try:
        run_osascript(script, timeout=15)
        return f"Replied to email #{message_number}"
    except Exception as e:
        return f"Failed to reply: {e}"
