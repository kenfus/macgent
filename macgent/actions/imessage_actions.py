import logging
from macgent.perception.safari import run_osascript

logger = logging.getLogger("macgent.actions.imessage")


def read_messages(contact: str = "", limit: int = 10) -> str:
    """Read recent iMessages. If contact is given, filter by that contact."""
    if contact:
        # Read messages from a specific contact
        escaped = contact.replace('"', '\\"')
        script = f'''
        tell application "Messages"
            set output to ""
            set msgCount to 0
            repeat with chat in text chats
                set participants to participants of chat
                set matched to false
                repeat with p in participants
                    if handle of p contains "{escaped}" or name of p contains "{escaped}" then
                        set matched to true
                        exit repeat
                    end if
                end repeat
                if matched then
                    -- Get chat name
                    set chatName to name of chat
                    set output to output & "Chat with: " & chatName & linefeed
                    -- Messages are not directly iterable in all macOS versions
                    -- So we use the chat's recent messages
                    set output to output & "Last message: " & (get the text of the last item of messages of chat) & linefeed
                    set msgCount to msgCount + 1
                    if msgCount >= {limit} then exit repeat
                end if
            end repeat
            if output is "" then
                return "No messages found for: {escaped}"
            end if
            return output
        end tell
        '''
    else:
        # Read most recent messages across all chats
        script = f'''
        tell application "Messages"
            set output to ""
            set chatList to text chats
            set maxChats to {min(limit, 10)}
            repeat with i from 1 to (count of chatList)
                if i > maxChats then exit repeat
                set chat to item i of chatList
                set chatName to name of chat
                try
                    set lastMsg to text of last item of messages of chat
                    set output to output & chatName & ": " & lastMsg & linefeed
                end try
            end repeat
            if output is "" then
                return "No recent messages found."
            end if
            return output
        end tell
        '''
    try:
        return run_osascript(script, timeout=15)
    except Exception as e:
        return f"Could not read messages: {e}"


def send_message(contact: str, text: str) -> str:
    """Send an iMessage to a contact (phone number or email)."""
    escaped_contact = contact.replace('"', '\\"')
    escaped_text = text.replace('"', '\\"')

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{escaped_contact}" of targetService
        send "{escaped_text}" to targetBuddy
    end tell
    '''
    try:
        run_osascript(script, timeout=15)
        return f"Sent message to {contact}: {text}"
    except Exception as e:
        # Fallback: try using buddy instead of participant
        script2 = f'''
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to buddy "{escaped_contact}" of targetService
            send "{escaped_text}" to targetBuddy
        end tell
        '''
        try:
            run_osascript(script2, timeout=15)
            return f"Sent message to {contact}: {text}"
        except Exception as e2:
            return f"Failed to send message: {e2}"
