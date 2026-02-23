# Skill: Notion Board (Leonardo's Planning Area)

## Overview

The Notion board is the CEO-visible task tracker. Every task the CEO cares about must appear here.
Database ID: set via `NOTION_PLANNING_DATABASE_ID` in `.env`

## Task Properties

| Property    | Values |
|-------------|--------|
| Name        | Task title (imperative, short) |
| Status      | Inbox → Ready → In Progress → Done / Blocked |
| Priority    | P1 Critical, P2 High, P3 Normal, P4 Low |
| Description | Full task details |
| Source      | `email:sender`, `telegram`, `manual` |
| MacgentID   | Internal task ID |
| Notes       | Result summary, progress updates, blocker reason |

## Status Lifecycle

```
CEO creates task → Manager enhances → Notion: Ready
Worker claims    → Notion: In Progress
Worker finishes  → Notion: Done    (with Notes summary)
Worker blocked   → Notion: Blocked (with Notes explaining what's needed)
Manager reads    → asks CEO via Telegram → CEO replies → Notion: Ready (re-queued)
```

## Worker: `notion_update` Action

The Worker uses `notion_update` to communicate progress and blockers:

```json
{"type": "notion_update", "params": {"note": "Step 2/5: Entering dates on booking.com"}}
{"type": "notion_update", "params": {"status": "Blocked", "note": "Need to know: Basel city center or airport area?"}}
```

Status values: `In Progress`, `Done`, `Blocked`. Omit status to just add a progress note.

**The Worker NEVER sends Telegram messages.** It only updates the Notion board.

## Manager Rules

- Never create a Notion task before asking for clarification (ask first, create after)
- Every actionable task from CEO or email must have a Notion entry
- Update Notes when marking Done or Blocked
- On heartbeat: check for "Blocked" tasks, read Notes, ask CEO a clear question via Telegram

## Worker Rules

- Update status to **In Progress** when claiming the task
- Use `notion_update` to add progress notes during execution
- When done: call `done` — system sets Notion to **Done** with summary
- When blocked: call `fail` — system sets Notion to **Blocked** with reason in Notes

## Priority Guidelines

- **P1 Critical** — urgent deadlines, system outages, direct CEO requests
- **P2 High** — important deliverables, client requests, time-sensitive
- **P3 Normal** — regular tasks, routine work
- **P4 Low** — nice-to-have, non-urgent
