# macgent Skills

This directory contains documentation for all available skills that macgent agents can use. These skills define what the agents can do and how to use them.

## Core Skills

### [Browser Automation](./browser_automation.md)
Control Safari browser, navigate pages, click elements, type text, and extract information from web pages.

### [Email Operations](./email_operations.md)
Read emails from Mail app, send emails, parse email content, and search email archives.

### [Calendar Operations](./calendar_operations.md)
Read calendar events, check availability, parse event details, and understand meeting schedules.

### [Messages (iMessage)](./messages.md)
Send and read iMessages, parse message threads, and communicate via Apple's messaging platform.

### [AppleScript Automation](./applescript.md)
Execute AppleScript commands, automate macOS applications, and control system features.

### [JavaScript Execution](./javascript.md)
Run JavaScript in browser pages, extract DOM data, and interact with single-page applications.

## How Agents Use Skills

Agents use skills through the **reasoning layer** (LLM). When deciding what to do:

1. The agent observes the current state (screenshot, page text, interactive elements)
2. The LLM reasons about what action to take based on the current state and task
3. The LLM chooses a skill (e.g., "click", "type", "scroll")
4. The dispatcher executes the skill with specific parameters
5. The result is fed back to the agent for the next observation

## For Developers

When agents don't know how to do something, it means:

- The skill documentation is missing or unclear
- The agent's system prompt doesn't explain the skill well enough
- The action dispatcher doesn't support that skill
- The agent needs an example or more guidance in its soul

To add a new skill:

1. Create a new `skill_name.md` file describing:
   - What the skill does
   - How to use it (with examples)
   - Common patterns and gotchas
   - When to use it vs alternatives

2. Implement the skill in the action dispatcher
3. Add it to the agent's system prompt (in `macgent/prompts/`)
4. Test with an example script

## Index

- [Browser Automation](./browser_automation.md) - Safari navigation and interaction
- [Email Operations](./email_operations.md) - Reading/sending emails via Mail app
- [Calendar Operations](./calendar_operations.md) - Calendar event management
- [Messages](./messages.md) - iMessage operations
- [AppleScript](./applescript.md) - macOS automation scripting
- [JavaScript](./javascript.md) - Web page JavaScript execution
