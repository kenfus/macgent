import json
import re
import logging
from macgent.models import Action, Observation, Step
from macgent.prompts.system_prompt import SYSTEM_PROMPT, build_user_message
from macgent.reasoning.llm_client import LLMClient

logger = logging.getLogger("macgent.reasoner")


def _extract_json(text: str) -> dict | None:
    """Try multiple strategies to extract JSON from LLM output."""
    text = text.strip()

    # Strip thinking tokens (DeepSeek-R1, Qwen3, etc.)
    if "<think>" in text:
        parts = text.split("</think>")
        text = parts[-1].strip() if len(parts) > 1 else text

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Strip markdown code blocks
    if "```" in text:
        # Try extracting from ```json ... ``` or ``` ... ```
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Strategy 3: Find first { ... } block (greedy from first { to last })
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    # Strategy 4: Find balanced braces from first {
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        break

    # Strategy 5: Try to fix common issues (single quotes, trailing commas)
    if start >= 0 and end > start:
        candidate = text[start:end]
        # Replace single quotes with double quotes (naive but helps)
        fixed = candidate.replace("'", '"')
        # Remove trailing commas before } or ]
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    return None


def get_next_action(client: LLMClient, task: str, observation: Observation,
                    history: list[Step], soul: str = "") -> Action:
    """Ask the reasoning LLM for the next action."""
    user_msg = build_user_message(task, observation, history)
    messages = [{"role": "user", "content": user_msg}]

    # Prepend soul to system prompt if provided
    system = (soul.strip() + "\n\n---\n\n" + SYSTEM_PROMPT) if soul.strip() else SYSTEM_PROMPT

    try:
        response_text = client.chat(
            messages=messages,
            system=system,
            max_tokens=2048,
            temperature=0.0,
        )
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return Action(type="wait", params={"seconds": 3}, reasoning=f"LLM error: {e}")

    logger.debug(f"LLM response: {response_text[:500]}")

    data = _extract_json(response_text)
    if data is None:
        logger.warning(f"Failed to parse LLM response: {response_text[:300]}")
        return Action(type="wait", params={"seconds": 2}, reasoning="Failed to parse LLM response")

    # Handle both {"action": {...}} and flat {"type": ...} formats
    action_data = data.get("action", data)

    action_type = action_data.get("type", "wait")
    params = action_data.get("params", {})
    reasoning = data.get("reasoning", "")

    # Ensure params is a dict
    if not isinstance(params, dict):
        params = {}

    return Action(type=action_type, params=params, reasoning=reasoning)
