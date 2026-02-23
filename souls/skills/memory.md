# Skill: Memory System

## On Wakeup — What Gets Loaded Automatically

Every time you're activated, your context includes:

1. **`soul.md`** — your personality, rules, and workflow
2. **`MEMORY.md`** — your curated long-term memory
3. **Today's daily log** (`~/.macgent/memories/memory-YYYY-MM-DD.md`)
4. **Last 2 days' logs** — rolling 3-day window of recent events
5. **Semantic recall** — FAISS fetches the most relevant past lessons for the current task

You don't need to load these manually — they're injected into your context.

## Daily Memory Files

- **Location:** `~/.macgent/memories/memory-YYYY-MM-DD.md`
- **Purpose:** Raw, timestamped event log
- **Written:** Automatically when something happens (not during HEARTBEAT_OK)
- **Format:**
  ```
  # Memory Log — 2026-02-23

  ## 14:30
  Checked email. 2 newsletters skipped. 1 task created: "Reply to Lisa about flowers" (P3).
  ```

## Curated Memory (MEMORY.md)

- **Location:** `souls/{role}/MEMORY.md`
- **Purpose:** Distilled long-term wisdom — patterns, CEO preferences, recurring facts
- **Rule:** Keep it small. Link to daily files for details.
- **Maintenance:** Review and update every few days during a spare heartbeat

## Semantic Recall

Before any task, FAISS automatically finds the most relevant past memories.
This surfaces lessons like:
- "booking.com shows cookie popup — click Reject at index [2] first"
- "CEO prefers hotels with rating ≥ 8.5 and proximity to meeting location"

No manual action needed — it runs automatically.

## Writing to Memory

- Important events are written to the daily log automatically
- After each task, the Worker extracts a lesson (category: lesson/pattern/preference/contact/fact)
- Do NOT write for HEARTBEAT_OK (empty heartbeats)

## 📝 No Mental Notes

Memory doesn't survive session restarts. Files do.
- Learn something? → daily log or MEMORY.md
- Make a mistake? → document it so future-you doesn't repeat it
