import json
import logging
from macgent.models import Action, Observation, Step
from macgent.prompts.system_prompt import SYSTEM_PROMPT, build_user_message
from macgent.reasoning.llm_client import LLMClient

logger = logging.getLogger("macgent.reasoner")


def get_next_action(client: LLMClient, task: str, observation: Observation, history: list[Step]) -> Action:
    """Ask the reasoning LLM for the next action."""
    user_msg = build_user_message(task, observation, history)
    messages = [{"role": "user", "content": user_msg}]

    response_text = client.chat(
        messages=messages,
        system=SYSTEM_PROMPT,
        max_tokens=1024,
        temperature=0.0,
    )

    logger.debug(f"LLM response: {response_text[:500]}")

    # Parse JSON from response
    try:
        text = response_text.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from mixed text
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(response_text[start:end])
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse LLM response: {response_text[:200]}")
                return Action(type="wait", params={"seconds": 2}, reasoning="Failed to parse LLM response")
        else:
            logger.warning(f"No JSON found in LLM response: {response_text[:200]}")
            return Action(type="wait", params={"seconds": 2}, reasoning="No JSON in LLM response")

    action_data = data.get("action", data)  # Handle both {"action": {...}} and flat format
    return Action(
        type=action_data.get("type", "wait"),
        params=action_data.get("params", {}),
        reasoning=data.get("reasoning", ""),
    )
