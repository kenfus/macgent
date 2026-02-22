import time
import logging
from macgent.config import Config
from macgent.models import AgentState, Step, Observation, Action
from macgent.perception.safari import (
    get_safari_url, get_safari_title, get_page_text,
    get_page_interactive_elements, get_page_structure,
    wait_for_page_load,
)
from macgent.perception.screenshot import (
    take_safari_window_screenshot, resize_screenshot, screenshot_to_base64,
)
from macgent.reasoning.llm_client import LLMClient
from macgent.reasoning.vision import describe_screenshot
from macgent.reasoning.reasoner import get_next_action
from macgent.actions.dispatcher import dispatch

logger = logging.getLogger("macgent")

SPA_DOMAINS = ["notion.so", "notion.com", "booking.com", "app.notion.so"]

# Actions that trigger page loads
NAVIGATION_ACTIONS = {"navigate", "go_back", "go_forward", "click", "click_element", "new_tab", "switch_tab"}


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
        print(f"Model: {self.config.reasoning_model}")
        if self.vision_client:
            print(f"Vision: {self.config.vision_model}")
        print(f"{'='*60}\n")

        last_action_type = None
        stuck_count = 0

        for step_num in range(1, state.max_steps + 1):
            print(f"\n--- Step {step_num}/{state.max_steps} ---")

            # Wait for page load after navigation actions
            if state.steps and state.steps[-1].action.type in NAVIGATION_ACTIONS:
                wait_for_page_load(timeout=5)
                time.sleep(0.5)

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
            print(f"  Think: {action.reasoning[:120]}")
            print(f"  Action: {action.type} {action.params}")

            # Stuck detection
            if action.type == last_action_type and action.type == "wait":
                stuck_count += 1
            else:
                stuck_count = 0
            last_action_type = action.type

            if stuck_count >= 3:
                print("  [!] Stuck in wait loop, scrolling")
                action = Action(type="scroll", params={"direction": "down", "amount": 500},
                                reasoning="Stuck - scrolling to discover more")

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
                print(f"  Result: {result[:120]}")
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

        try:
            obs.url = get_safari_url()
            obs.page_title = get_safari_title()
        except Exception:
            # Safari has no window open — open a blank one and report no page yet
            try:
                from macgent.actions.safari_actions import ensure_safari_window
                ensure_safari_window()
                obs.url = "about:blank"
                obs.page_title = "New window opened"
                obs.page_text = "(No page loaded yet. Use navigate to go to a URL.)"
            except Exception as e:
                obs.error = f"Safari not accessible: {e}"
            return obs

        # Page structure + text + elements
        try:
            structure = get_page_structure()
            page_text = get_page_text(self.config.page_text_max_chars)
            elements = get_page_interactive_elements()

            parts = []
            if structure:
                parts.append(structure)
            if page_text:
                text_budget = self.config.page_text_max_chars
                if len(page_text) > text_budget:
                    page_text = page_text[:text_budget] + "..."
                parts.append(f"\nPAGE TEXT:\n{page_text}")
            if elements:
                parts.append(f"\nELEMENTS:\n{elements}")

            obs.page_text = "\n".join(parts)
        except Exception as e:
            obs.page_text = f"(page extraction failed: {e})"

        # Vision for SPAs or sparse pages
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
