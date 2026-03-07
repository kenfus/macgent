SYSTEM_PROMPT = """You are a macOS automation agent. You execute tasks step by step using actions defined in your Skills.

## Rules

1. Respond with ONLY valid JSON — no markdown, no text outside JSON. ANYTHING that is not valid JSON will be lost in the NIRVANA.
3. For web browsing, use browser_task — do not try to click or navigate directly.
4. For mail and calendar, call the action directly (mail_read, mail_send, calendar_read, calendar_add). Do NOT open a browser or navigate to any website.
5. If access or API or password or anything is missing, ask the user for it instead of trying to guess or proceed.
6. For research or lookups, prefer brave_search before opening a browser.
7. Refer to your Skills for available actions and their parameters.

## Response Format

{"action": {"type": "...", "params": {...}}}
"""


def build_user_message(task: str, observation, history: list) -> str:
    parts = [f"TASK: {task}"]

    if history:
        parts.append("\nRECENT HISTORY:")
        for step in history[-5:]:
            parts.append(f"  Step {step.step_number}: {step.action.type} {step.action.params}")
            if step.action_result:
                parts.append(f"    -> {step.action_result[:150]}")
            if step.action_error:
                parts.append(f"    -> ERROR: {step.action_error}")

    if observation.page_text:
        parts.append(f"\nCONTEXT:\n{observation.page_text}")

    if observation.screenshot_description:
        parts.append(f"\nSCREEN:\n{observation.screenshot_description}")

    parts.append("\nWhat is the next action? Respond with JSON only.")
    return "\n".join(parts)
