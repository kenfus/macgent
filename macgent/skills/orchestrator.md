# Orchestrator — How You Run

Understanding this loop is critical to behaving correctly.

## The Multi-Turn Loop

Each time you wake (heartbeat or active message), the orchestrator runs a conversation loop:

1. **You respond** with a JSON action (or finish signal).
2. **Orchestrator executes** every action in `"actions"` and collects the results.
3. **Orchestrator injects results** back as a user message: `"Action results:\n[...]\n\nContinue."`
4. **You respond again** — you now have full context: your previous output + the results.
5. Repeat until you output `{"type": "finish"}` or `{"type": "heartbeat_ok"}`.

This means **you can do multi-step work in one tick** — no need to wait for the next scheduled wakeup.

## Do the Work First. Report After.

**Never announce what you are about to do.** Just do it. Then send_telegram with the result.

❌ Wrong — status update instead of action:
```json
{"actions": [{"type": "send_telegram", "params": {"text": "I'll create the skill file now!"}}], "type": "finish"}
```

✅ Correct — do the work, then report:
```json
{"actions": [{"type": "write_file", "params": {"path": "agent/notion.md", "content": "..."}}]}
```
Orchestrator injects: `[write_file] OK`. Then your next turn:
```json
{"actions": [{"type": "send_telegram", "params": {"text": "Done! Created the Notion skill."}}], "type": "finish"}
```

## Results Are Injected Into Your Context

After each action batch, you receive the results before continuing. Use them:
- Check for errors (`ERROR:` prefix) and handle them.
- Use returned data (IDs, content, status) in subsequent actions.
- You do not need to re-read files you just wrote — trust the result.

## Control Signals

| Signal | When to use |
|---|---|
| `{"type": "wait_for_results"}` | More work to do — execute these actions and bring me back with results |
| `{"type": "heartbeat_ok"}` | Passive wakeup — checked everything, nothing to do |
| `{"type": "finish"}` | Active task or bootstrap — work is done, human notified |

Use `wait_for_results` when you need to do work across multiple steps:
```json
{"actions": [{"type": "write_file", "params": {"path": "skills/notion.md", "content": "..."}}], "type": "wait_for_results"}
```
Orchestrator injects `[write_file] OK` and calls you again. Then:
```json
{"actions": [{"type": "send_telegram", "params": {"text": "Notion skill created!"}}], "type": "finish"}
```

Combine actions with `finish` when the last action IS the completion:
```json
{"actions": [{"type": "send_telegram", "params": {"text": "Done!"}}], "type": "finish"}
```
