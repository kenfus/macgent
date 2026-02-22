import time
import logging
from macgent.config import Config
from macgent.models import AgentState, Step, Observation, Action
from macgent.perception.safari import (
    get_safari_url, get_safari_title, get_page_text,
    get_page_interactive_elements, wait_for_page_load,
)
from macgent.perception.screenshot import (
    take_safari_window_screenshot, resize_screenshot, screenshot_to_base64,
)
from macgent.reasoning.llm_client import LLMClient
from macgent.reasoning.vision import describe_screenshot
from macgent.reasoning.reasoner import get_next_action
from macgent.actions.dispatcher import dispatch

logger = logging.getLogger("macgent")

# Domains where we always use screenshots (heavy SPAs)
SPA_DOMAINS = ["notion.so", "notion.com", "booking.com", "app.notion.so"]


class Agent:
    def __init__(self, config: Config):
        self.config = config
        self.reasoning_client = LLMClient(
            config.reasoning_api_base, config.reasoning_api_key,
            config.reasoning_model, config.reasoning_api_type,
        )
        self.vision_client = None
        if config.use_vision and config.vision_api_key:
            self.vision_client = LLMClient(
                config.vision_api_base, config.vision_api_key,
                config.vision_model, config.vision_api_type,
            )

    def run(self, task: str) -> AgentState:
        state = AgentState(task=task, max_steps=self.config.max_steps)

        print(f"\n{'='*60}")
        print(f"Task: {task}")
        print(f"Reasoning: {self.config.reasoning_model} ({self.config.reasoning_api_type})")
        if self.vision_client:
            print(f"Vision: {self.config.vision_model} ({self.config.vision_api_type})")
        else:
            print("Vision: disabled")
        print(f"{'='*60}\n")

        for step_num in range(1, state.max_steps + 1):
            print(f"--- Step {step_num} ---")

            # 1. OBSERVE
            last_action_str = ""
            if state.steps:
                last = state.steps[-1]
                last_action_str = f"{last.action.type} {last.action.params}"

            observation = self._observe(task, last_action_str)
            print(f"  URL: {observation.url}")
            print(f"  Title: {observation.page_title}")

            # 2. THINK
            action = self._think(task, observation, state.steps)
            print(f"  Reasoning: {action.reasoning[:120]}...")
            print(f"  Action: {action.type} {action.params}")

            # 3. Record step
            step = Step(step_number=step_num, observation=observation, action=action)

            # 4. Terminal?
            if action.type == "done":
                step.action_result = "Task completed"
                state.steps.append(step)
                state.status = "completed"
                print(f"\n  DONE: {action.params.get('summary', '')}")
                break
            elif action.type == "fail":
                step.action_result = "Task failed"
                state.steps.append(step)
                state.status = "failed"
                print(f"\n  FAILED: {action.params.get('reason', '')}")
                break

            # 5. ACT
            try:
                result = dispatch(action)
                step.action_result = result
                print(f"  Result: {result[:100]}")
            except Exception as e:
                step.action_error = str(e)
                print(f"  Error: {e}")

            state.steps.append(step)
            time.sleep(self.config.step_delay)
        else:
            state.status = "failed"
            print(f"\nMax steps ({state.max_steps}) reached")

        return state

    def _observe(self, task: str, last_action: str = "") -> Observation:
        obs = Observation()

        # Always try Safari state
        try:
            obs.url = get_safari_url()
            obs.page_title = get_safari_title()
        except Exception as e:
            # Safari might not be open - that's ok for non-browser tasks
            obs.error = f"Safari not accessible: {e}"
            return obs

        # Get page text + interactive elements
        try:
            page_text = get_page_text(self.config.page_text_max_chars)
            elements = get_page_interactive_elements()
            obs.page_text = f"PAGE TEXT:\n{page_text}\n\nINTERACTIVE ELEMENTS:\n{elements}"
        except Exception as e:
            obs.page_text = f"(page text extraction failed: {e})"

        # Vision: screenshot + description for SPAs or sparse pages
        is_spa = any(d in (obs.url or "") for d in SPA_DOMAINS)
        text_sparse = len(obs.page_text or "") < 200

        if self.vision_client and (is_spa or text_sparse):
            try:
                path = take_safari_window_screenshot()
                resized = resize_screenshot(path, self.config.screenshot_max_width)
                img_b64 = screenshot_to_base64(resized)
                obs.screenshot_b64 = img_b64
                obs.screenshot_description = describe_screenshot(
                    self.vision_client, img_b64, task, last_action,
                )
            except Exception as e:
                logger.warning(f"Vision failed: {e}")

        return obs

    def _think(self, task: str, observation: Observation, history: list[Step]) -> Action:
        return get_next_action(self.reasoning_client, task, observation, history)
