# Core Memory Contract

This describes how your memory system works.

## Memory Retrieval Policy

You always receive:
- This core memory file
- Longterm memory files
- Recent daily memory logs (today + yesterday by default)
- Top-N relevant semantic memory chunks for the current task

Daily memory logs are stored at `{{WORKSPACE_DIR}}/memory/<YYYY-MM-DD>_MEMORY.md`.
If you need to remember something quickly, use `append_to_daily_memory`.

## Memory Usage Rules

- Use recalled memory as guidance, not absolute truth.
- Prefer recent memory when there is a conflict.
- If memory appears stale or wrong, continue task execution and add a corrected lesson.
- Keep lessons specific and reusable.

## Update Policy

- Add new memories to daily logs.
- Add new lessons to daily logs.
- Add new semantic memories to the semantic memory store.
- Add new role memories to the role memory file.

At night, distill important points into `{{WORKSPACE_DIR}}/agent/memory/LONGTERM_MEMORY.md`.
