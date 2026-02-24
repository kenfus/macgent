# Notion Board Reference

## Property Names & Types
- **Title** – Title (text)
- **Status** – Status (select)
- **Priority** – Priority (multi_select)
- **Notes** – Notes (text)
- **Created Time** – Created Time (created_time)

## Status Values & Meaning
- **Backlog** – Not ready yet / waiting for input
- **Ready** – Awaiting work (the Worker will start it)
- **In Progress** – Currently being worked on
- **Blocked** – Task is blocked; notes contain the blocker and a question for the CEO
- **Done** – Completed

## Priority Values
- **High** – Urgent, time‑sensitive
- **Medium** – Important but not urgent
- **Low** – Nice‑to‑have or low impact

## Common Filter Examples
- **Get all blocked tasks**:
  {"filter": {"property": "Status", "select": {"equals": "Blocked"}}}
- **Get all ready tasks**:
  {"filter": {"property": "Status", "select": {"equals": "Ready"}}}
- **Get high‑priority tasks**:
  {"filter": {"property": "Priority", "multi_select": {"contains_any": [{"name": "High"}]}}}

## Property Update Examples
- **Set status to "In Progress"**:
  {"op": "set", "property": "Status", "select": {"name": "In Progress"}}
- **Add a note**:
  {"op": "set", "property": "Notes", "rich_text": {"content": "New update"}}
- **Create a new task** (example payload):
  {
    "properties": {
      "Title": {"title": [{"text": {"content": "New Task"}}]},
      "Status": {"select": {"name": "Backlog"}},
      "Priority": {"multi_select": [{"name": "Medium"}]}
    }
  }

## Worker Rules
- The Worker **never** sends Telegram messages.
- The Worker updates the Notion board only via `notion_update` or `notion_create`.
- When a task is blocked, the Worker sets the **Status** to **Blocked** and writes the blocker + a question in **Notes**.

## Manager Rules
- The Manager reads blocked tasks, formulates a single clear question, and sends it to the CEO via Telegram.
- The Manager creates new tasks via `notion_create` after receiving CEO approval or after clarifying an ambiguous request.
- The Manager skips newsletters, system notifications, and empty heartbeats.

---
*This skill will be refreshed automatically when the board schema changes.*