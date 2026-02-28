import json
import time
import logging

from macgent.config import Config
from macgent.models import AgentState, Step, Observation, Action
from macgent.reasoning.llm_client import build_text_fallback_client
from macgent.reasoning.reasoner import get_next_action
from macgent.actions.dispatcher import dispatch

logger = logging.getLogger("macgent")

MACOS_DIRECT_KEYWORDS = (
    "email",
    "mail",
    "inbox",
    "calendar",
    "meeting",
    "imessage",
    "message",
    "sms",
)


class Agent:
    def __init__(self, config: Config, db=None, task_id: str | None = None,
                 memory=None, task_description: str = ""):
        self.config = config
        self.db = db
        self.task_id = task_id
        self.reasoning_client = build_text_fallback_client(config)

        # Build full agent soul: soul + skills + memory + semantic recall
        if memory and db:
            self.soul = memory.build_context(
                db, "agent", task_id=task_id, task_description=task_description
            )
            logger.info("Loaded agent soul via MemoryManager (full context)")
        else:
            self.soul = self._load_soul("agent")

    def _load_soul(self, role: str) -> str:
        """Load soul file from workspace/{role}/SOUL.md (fallback: soul.md)."""
        from pathlib import Path

        workspace = Path(self.config.workspace_dir)
        candidates = [workspace / role / "SOUL.md", workspace / role / "soul.md"]
        for path in candidates:
            if path.exists():
                logger.info(f"Loaded {role} soul from {path}")
                return path.read_text().replace("{{WORKSPACE_DIR}}", str(workspace))
        logger.debug(f"No soul file for {role} at {candidates[0]}")
        return ""

    def run(self, task: str) -> AgentState:
        state = AgentState(task=task, max_steps=self.config.max_steps)

        print(f"\n{'=' * 60}")
        print(f"Task: {task}")
        print(f"Model: {self.config.reasoning_model}")
        print(f"Browser mode: {self.config.browser_mode}")
        print(f"{'=' * 60}\n")

        # macOS tasks use direct action loop (no Safari perception).
        if self._is_macos_direct_task(task):
            return self._run_macos_direct_loop(state, task)

        # All web tasks delegate to agent-browser adapter.
        return self._run_browser_task_delegate(state, task, reason="primary_mode")

    def _is_macos_direct_task(self, task: str) -> bool:
        task_l = task.lower()
        return any(keyword in task_l for keyword in MACOS_DIRECT_KEYWORDS)

    def _run_macos_direct_loop(self, state: AgentState, task: str) -> AgentState:
        """Run a direct-action LLM loop for macOS native actions (Mail/Calendar/iMessage)."""
        last_action_key = None
        stuck_count = 0

        for step_num in range(1, state.max_steps + 1):
            print(f"\n--- Step {step_num}/{state.max_steps} ---")

            observation = Observation(
                url="macos://local",
                page_title="macOS direct actions",
                page_text=(
                    "Use direct native actions when possible: mail_read/mail_send, "
                    "calendar_read/calendar_add, imessage_read/imessage_send."
                ),
            )

            action = self._think(task, observation, state.steps)
            print(f"  Think: {action.reasoning[:120]}")
            print(f"  Action: {action.type} {action.params}")

            action_key = (action.type, json.dumps(action.params, sort_keys=True))
            if action_key == last_action_key:
                stuck_count += 1
            else:
                stuck_count = 0
            last_action_key = action_key

            step = Step(step_number=step_num, observation=observation, action=action)

            if action.type == "done":
                step.action_result = "Task completed"
                state.steps.append(step)
                state.status = "completed"
                print(f"\n  DONE: {action.params.get('summary', '')}")
                break
            if action.type == "fail":
                step.action_result = "Task failed"
                state.steps.append(step)
                state.status = "failed"
                print(f"\n  FAILED: {action.params.get('reason', '')}")
                break

            try:
                result = dispatch(action)
                step.action_result = result
                print(f"  Result: {str(result)[:120]}")
            except Exception as e:
                step.action_error = str(e)
                print(f"  Error: {e}")

            state.steps.append(step)

            if stuck_count >= 3:
                state.status = "failed"
                print("\n  FAILED: Stuck repeating same action in macOS direct loop")
                break

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

    def _run_browser_task_delegate(self, state: AgentState, task: str, reason: str) -> AgentState:
        """Delegate browsing to the browser task adapter and map response to AgentState."""
        action = Action(
            type="browser_task",
            params={
                "task": task,
                "mode": self.config.browser_mode,
                "max_steps": self.config.max_steps,
                "capture_artifacts": True,
            },
            reasoning=f"Delegated to browser_task ({reason})",
        )
        obs = Observation(url="agent-browser://delegate", page_title="Delegated browser task")
        step = Step(step_number=len(state.steps) + 1, observation=obs, action=action)

        result_raw = dispatch(action)
        step.action_result = result_raw
        state.steps.append(step)

        try:
            payload = json.loads(result_raw)
        except Exception:
            payload = {"solved": False, "blocked_reason": "invalid_browser_task_result", "raw": result_raw}

        solved = bool(payload.get("solved"))
        state.status = "completed" if solved else "failed"

        logger.info(
            "browser_delegate_done reason=%s solved=%s blocked_reason=%s artifact_dir=%s",
            reason,
            solved,
            payload.get("blocked_reason"),
            payload.get("artifact_dir"),
        )
        return state

    def _think(self, task: str, observation: Observation, history: list[Step]) -> Action:
        return get_next_action(self.reasoning_client, task, observation, history, soul=self.soul)
