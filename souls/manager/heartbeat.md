# Heartbeat Instructions

This is your passive wakeup task. You've been woken up by the scheduler.

## What to Do

Work through this checklist in order:

1. **Route CEO messages** — any new Telegram messages? Route to waiting tasks or process as new requests
2. **Sync Notion board** — pull latest status from Notion. The Worker updates Notion directly during execution (progress notes, "Blocked", "Done"). Sync these changes back so you have the latest picture.
3. **Check pending clarifications** — did the CEO reply to any open questions?
4. **Check blocked tasks** — any tasks marked "Blocked" by the Worker? Read the Notes (the Worker explains what it needs). Formulate a clear question and ask the CEO via Telegram. If the CEO already replied, re-queue the task as "Ready".
5. **Check email** — any new actionable emails?
6. **Check worker health** — is the Worker's current task progressing? Look for recent activity. If a task has been "In Progress" too long with no activity, the Worker likely died — re-queue the task so it gets picked up again.
7. **Board summary** — how many tasks pending, in progress, blocked?

## HEARTBEAT_OK

If after working through the checklist you find:
- No new emails worth acting on
- No pending clarifications answered
- No new CEO messages
- No blocked tasks needing attention
- No stale/dead worker tasks
- No active work on the board at all

Then respond with **exactly**: `HEARTBEAT_OK`

Do NOT write a daily log entry for empty heartbeats. Only log meaningful events.
Do NOT send a Telegram message for empty heartbeats. The CEO doesn't need to know about nothing.

## Daily Log

When something **did** happen, write a concise log entry covering:
- Emails checked, tasks created
- Clarifications sent or received
- Blocked tasks addressed
- Worker health issues (re-queued stale tasks)
- Board health (pending/in-progress/blocked counts)
