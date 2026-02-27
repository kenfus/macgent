# Skill: Memory System

## On Wakeup — What Gets Loaded Automatically

Every time you're activated, your context includes:

1. **`soul.md`** — your personality, rules, and workflow
2. **`core_memory.md`** — global memory contract (always injected)
3. **`<role>/MEMORY.md`** — optional curated role memory
4. **Today's and yesterday's daily logs** (`workspace/memory/daily/memory-YYYY-MM-DD.md`)
5. **Top-N semantic recall chunks** from `workspace/memory/semantic_memories.jsonl`

You don't need to load these manually — they're injected into your context.

## Daily Memory Files

- **Location:** `workspace/memory/daily/memory-YYYY-MM-DD.md`
- **Purpose:** Raw, timestamped event log
- **Written:** Automatically when something happens (not during HEARTBEAT_OK)
- **Format:**
  ```
  # Memory Log — 2026-02-23

  ## 14:30
  Checked email. 2 newsletters skipped. 1 task created: "Reply to Lisa about flowers" (P3).
  ```

## Curated Memory (MEMORY.md)

- **Location:** `workspace/{role}/MEMORY.md`
- **Purpose:** Distilled long-term wisdom — patterns, CEO preferences, recurring facts
- **Rule:** Keep it small. Link to daily files for details.
- **Maintenance:** Review and update every few days during a spare heartbeat

## Semantic Recall

Before any task, semantic recall automatically finds the most relevant past memories.
This surfaces lessons like:
- "booking.com shows cookie popup — click Reject at index [2] first"
- "CEO prefers hotels with rating ≥ 8.5 and proximity to meeting location"

No manual action needed — it runs automatically.

## Writing to Memory

- Important events are written to the daily log automatically
- After each task, the Worker extracts a lesson (category: lesson/pattern/preference/contact/fact)
- Do NOT write for HEARTBEAT_OK (empty heartbeats)

## 📝 No Mental Notes

Memory is file-based and survives restarts.
- Learn something? → daily log or MEMORY.md
- Make a mistake? → document it so future-you doesn't repeat it
