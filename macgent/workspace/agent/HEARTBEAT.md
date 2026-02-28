# Heartbeat Instructions

This is your passive wakeup task. You've been woken up by the scheduler.

## What to Do

Work through this checklist using your Notion skill doc for board-specific details (status names, filters, etc.):

1. **Query the Notion board** — use `notion_query` to see the current state. Check for:
   - Blocked tasks (read the Notes, formulate a clear question, ask CEO via `send_telegram`)
   - Stale in-progress tasks (agent execution likely died — update status back to ready)
   - Tasks waiting for clarification (did CEO reply? If so, update and move to ready)

2. **Check CEO messages** — any new messages provided in your context? If so:
   - If there's a task waiting for input, apply the CEO's answer and re-queue it
   - If it's a new request, create a Notion task (enhance it with a good title/description/priority)

3. **Check emails** — any new actionable emails listed in your context? Classify and create tasks.

4. **Board health** — how many tasks are ready, in progress, blocked? Only note if something needs attention.

## Response Format

Execute actions as JSON. Multiple actions per turn are fine:
```json
{"actions": [
  {"type": "notion_query", "params": {"filter": {...}}},
  {"type": "send_telegram", "params": {"text": "..."}}
]}
```

## HEARTBEAT_OK

If after checking everything you find nothing actionable:
- No blocked tasks needing attention
- No CEO messages to process
- No new emails worth acting on
- No stale tasks to re-queue
- Board looks healthy

Then respond with exactly: `HEARTBEAT_OK`

Do NOT send a Telegram message for empty heartbeats. The CEO doesn't need to know about nothing.
