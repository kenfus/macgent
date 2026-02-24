# Skill: Communication

## Who Can Send Telegram Messages

**Only the Manager sends Telegram messages to the CEO.** The Worker communicates exclusively through the Notion board (see [notion.md](notion.md)).

## Manager: Sending Messages to the CEO

### Via Telegram (preferred — fast, direct)

The Manager uses `send_telegram` to communicate with the CEO:
- Task completion notifications
- Clarification questions before creating tasks
- Questions about blocked tasks (reading the Worker's Notion notes)

### Via Email

```json
{"type": "mail_send", "params": {"to": "ceo@example.com", "subject": "Subject", "body": "Body"}}
```

## When to Communicate

**Do send (Manager only):**
- Task completed with key findings
- Clarification question: ONE focused question before creating a task
- Blocked task question: Worker is stuck, ask CEO what to do
- Something time-sensitive that can't wait for the next heartbeat

**Don't send:**
- Empty heartbeat updates (respond HEARTBEAT_OK silently)
- Routine status updates — Notion covers that
- Mid-task progress — Worker updates Notion, not Telegram
- Duplicates

## Message Format

Keep it concise. The CEO is busy.

| Situation  | Format |
|------------|--------|
| Completed  | `Got it! Created task: **[title]**` |
| Question   | `Quick question before I add this to the board: [question]?` |
| Blocked    | `Task **[title]** is blocked: [question from Worker's notes]` |
| Confirmed  | `Thanks! **[title]** is now on the board.` |
