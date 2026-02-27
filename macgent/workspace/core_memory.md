# Core Memory Contract

This file is always injected into every LLM call context, together with soul and skills.

## Memory Retrieval Policy

You always receive:
- This core memory file
- Recent daily memory logs (today + yesterday by default)
- Top-N relevant semantic memory chunks for the current task

Do not ask for this data explicitly; it is already included in your context.

## Memory Sources

- Daily logs: `memory/daily/memory-YYYY-MM-DD.md`
- Semantic memory store: `memory/semantic_memories.jsonl`
- Role memory (optional): `<role>/MEMORY.md`

## Memory Usage Rules

- Use recalled memory as guidance, not absolute truth.
- Prefer recent memory when there is a conflict.
- If memory appears stale or wrong, continue task execution and add a corrected lesson.
- Keep lessons specific and reusable.

## Skills Registry

Core skills are loaded from `macgent/skills/*.md`.
Learned skills are loaded from `workspace/skills/*.md` after core skills.
