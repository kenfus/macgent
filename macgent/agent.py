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

SPA_DOMAINS = ["notion.so", "notion.com", "booking.com", "app.notion.so", "docs.google.com"]
# Per-domain wait times after click/nav (seconds). Longer for complex JS rendering.
SPA_WAIT = {"booking.com": 2.5, "docs.google.com": 1.0}

# Actions that trigger page loads
NAVIGATION_ACTIONS = {"navigate", "go_back", "go_forward", "click", "click_element", "new_tab", "switch_tab"}


class Agent:
    def __init__(self, config: Config, db=None, task_id: str | None = None,
                 memory=None, task_description: str = ""):
        self.config = config
        self.db = db
        self.task_id = task_id
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

        # Build full worker soul: soul + skills + memory + semantic recall
        if memory and db:
            self.soul = memory.build_context(
                db, "worker", task_id=task_id, task_description=task_description
            )
            logger.info("Loaded worker soul via MemoryManager (full context)")
        else:
            self.soul = self._load_soul("worker")

    def _load_soul(self, role: str) -> str:
        """Load soul file from workspace/{role}/soul.md."""
        from pathlib import Path
        workspace = Path(self.config.workspace_dir)
        path = workspace / role / "soul.md"
        if path.exists():
            logger.info(f"Loaded {role} soul from {path}")
            return path.read_text()
        logger.debug(f"No soul file for {role} at {path}")
        return ""

    def run(self, task: str) -> AgentState:
        state = AgentState(task=task, max_steps=self.config.max_steps)

        print(f"\n{'='*60}")
        print(f"Task: {task}")
        print(f"Model: {self.config.reasoning_model}")
        if self.vision_client:
            print(f"Vision: {self.config.vision_model}")
        print(f"{'='*60}\n")

        last_action_key = None
        stuck_count = 0

        for step_num in range(1, state.max_steps + 1):
            print(f"\n--- Step {step_num}/{state.max_steps} ---")

            # Wait for page load after navigation actions
            if state.steps and state.steps[-1].action.type in NAVIGATION_ACTIONS:
                wait_for_page_load(timeout=5)
                # SPAs need extra time for React re-renders (date pickers, modals)
                try:
                    _url = get_safari_url()
                    _spa_wait = next((w for d, w in SPA_WAIT.items() if d in _url), None)
                    if _spa_wait is None and any(d in _url for d in SPA_DOMAINS):
                        _spa_wait = 1.5
                except Exception:
                    _spa_wait = None
                time.sleep(_spa_wait if _spa_wait else 0.5)

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

            # Stuck detection: catch repeated identical actions (wait OR same click index)
            action_key = (action.type, str(action.params.get("index", action.params.get("url", ""))))
            if action_key == last_action_key:
                stuck_count += 1
            else:
                stuck_count = 0
            last_action_key = action_key

            if stuck_count >= 3:
                print(f"  [!] Stuck repeating '{action.type}' — pressing Escape and scrolling up")
                # Try to dismiss any blocking overlay, then scroll to reveal more
                from macgent.actions.dispatcher import dispatch as _dispatch
                try:
                    _dispatch(Action(type="key_press", params={"key": "escape"}, reasoning="escape overlay"))
                except Exception:
                    pass
                action = Action(type="scroll", params={"direction": "up", "amount": 300},
                                reasoning="Stuck on same action — scrolling up to find what's blocking")

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

            # Log step to DB so manager can peek at progress
            if self.db and self.task_id:
                outcome = step.action_result or step.action_error or ""
                self.db.log(
                    "agent",
                    f"step_{step_num}:{action.type}",
                    f"{action.params} -> {outcome}"[:200],
                    self.task_id,
                )

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
        return get_next_action(self.reasoning_client, task, observation, history, soul=self.soul)
