# macgent Skills

This directory documents the skill system used by macgent agents.

## Skill Tiers

### Core Skills (always loaded)
Source: `macgent/skills/*.md`

- [Browser Automation](../macgent/skills/browser_automation.md)
- [Agent Browser](../macgent/skills/agent_browser.md)
- [Email Operations](../macgent/skills/email_operations.md)
- [Calendar Operations](../macgent/skills/calendar_operations.md)
- [Messages](../macgent/skills/messages.md)
- [AppleScript](../macgent/skills/applescript.md)
- [JavaScript](../macgent/skills/javascript.md)
- [macOS Direct Actions](../macgent/skills/macos.md)
- [Evaluate Image](../macgent/skills/evaluate_image.md)

Core skills must map to runtime actions in Python modules.

### Learned Skills (always loaded after core)
Source: `workspace/skills/*.md`

- Example: `workspace/skills/notion.md`

Learned skills are markdown-only references and do not require Python implementations.

## Runtime Mapping

- Browser action loop: `macgent/actions/dispatcher.py` + `macgent/actions/safari_actions.py`
- Browser delegation action: `browser_task` -> `macgent/actions/browser_use_action.py`
- macOS direct actions: `mail_actions.py`, `calendar_actions.py`, `imessage_actions.py`
- Skills loading order: `macgent/memory.py::load_skills`

## Source of Truth

See [docs/PROJECT_SETUP.md](../docs/PROJECT_SETUP.md) for the full authoring contract and extension workflow.
