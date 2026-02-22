import logging
from macgent.prompts.vision_prompt import VISION_SYSTEM_PROMPT, VISION_USER_PROMPT
from macgent.reasoning.llm_client import LLMClient

logger = logging.getLogger("macgent.vision")


def describe_screenshot(client: LLMClient, image_base64: str, task: str, last_action: str = "") -> str:
    """Use vision model to describe a screenshot."""
    extra = f"Last action taken: {last_action}" if last_action else ""
    prompt = VISION_USER_PROMPT.format(task=task, extra_context=extra)
    return client.chat_with_image(
        prompt=prompt,
        image_base64=image_base64,
        system=VISION_SYSTEM_PROMPT,
        max_tokens=800,
    )
