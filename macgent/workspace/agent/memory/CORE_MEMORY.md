# Core Memory Contract

This describes how your memory system works.

## What You Always Receive

Each tick your context includes (in order):

1. **Soul** — your personality and core rules (`agent/SOUL.md`)
2. **Identity** — your name and personal traits (`agent/IDENTITY.md`)
3. **Long-term Memory** — facts distilled from past workdays (`agent/memory/LONGTERM_MEMORY.md`)
4. **Yesterday's Memory** — full log of the previous workday
5. **Today's Memory** — what has happened so far this workday
6. **Skills** — all available actions and how to use them

## Workday Definition

A "workday" runs from **04:00 to 04:00** (next calendar day). Activity after midnight
but before 04:00 still counts as the *previous* workday. This matches real human schedules.

## Memory Files

All memory files live in `{{WORKSPACE_DIR}}/agent/memory/`:

| File | How to update |
|------|--------------|
| `YYYY-MM-DD_MEMORY.md` | Use `append_to_daily_memory` action — always use this |
| `LONGTERM_MEMORY.md` | Use `write_file` or `read_file` directly for permanent facts |
| `CORE_MEMORY.md` | This file — describes the memory system itself |

## Memory Rules

- Use recalled memory as guidance, not absolute truth.
- Prefer recent memory over older entries when there is a conflict.
- If memory appears stale or wrong, continue and add a corrected lesson.
- Keep lessons specific and reusable.

## Automatic Distillation

Each day at **04:00** the system pulse automatically:
1. Reads the completed workday's memory log
2. Asks the LLM: *"What from yesterday is worth remembering forever?"*
3. Appends important facts to `LONGTERM_MEMORY.md`
4. Deletes daily logs older than 2 workdays (you already have the distillation)

You can also update `LONGTERM_MEMORY.md` directly whenever you learn something important.

## Scheduled Wakeups (Pulse Schedule)

You can schedule yourself to wake at specific times by writing to
`{{WORKSPACE_DIR}}/agent/PULSE_SCHEDULE.json`:

```json
[
  {
    "id": "morning-briefing",
    "time": "09:00",
    "description": "Check calendar and send a morning summary to the CEO"
  }
]
```

Each entry fires once per workday. The pulse runs every 60 seconds and checks this file.
