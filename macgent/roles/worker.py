"""Worker role — executes tasks from Notion board and updates progress there.

The Worker NEVER messages the CEO directly. All communication goes through
the Notion board (via generic notion_update action). The Manager reads it
and talks to the CEO.
"""

import logging
from macgent.roles.base import BaseRole
from macgent.prompts.role_prompts import WORKER_LEARN_PROMPT
from macgent.actions.dispatcher import set_dispatch_config

logger = logging.getLogger("macgent.roles.worker")


class WorkerRole(BaseRole):
    role_name = "worker"

    def __init__(self, config, db, memory):
        super().__init__(config, db, memory)
        # Push config to dispatcher so Notion actions work
        set_dispatch_config(config)

    def tick(self):
        """Called each heartbeat: claim and run next Ready task from Notion.

        Note: In the new architecture, the Manager's LLM decides which task
        to assign. This tick() is a fallback for daemon mode where the worker
        runs independently.
        """
        from macgent.actions import notion_actions

        logger.info("Worker tick starting")
        self.db.log("worker", "tick_start")

        # Query Notion for ready tasks (worker uses generic query)
        tasks = notion_actions.notion_query(
            self.config.notion_token,
            self.config.notion_database_id,
        )
        # Find first task with a "ready"-like status (agent's skill doc defines the exact name)
        # Fallback heuristic: look for common ready-state names
        ready_task = None
        for t in tasks:
            status = (t.get("Status", "") or "").lower()
            if "ready" in status and "not" not in status:
                ready_task = t
                break

        if not ready_task:
            print("  Worker: No ready tasks")
            self.db.log("worker", "no_tasks")
            return

        # Find the title (could be any property name)
        title = ""
        for key in ("Task Name", "Name", "Title"):
            if key in ready_task:
                title = ready_task[key]
                break
        if not title:
            title = str(ready_task.get("page_id", "unknown"))[:20]

        print(f"  Worker: Claiming task '{title}'")
        self.run_task(ready_task)
        self.db.log("worker", "tick_done")

    def run_task(self, task: dict):
        """Execute a Notion task: claim -> execute -> learn.

        Args:
            task: Simplified Notion page dict (from notion_query/notion_get).
                  Must contain 'page_id'. Other fields depend on board layout.
        """
        page_id = task["page_id"]

        # Find title and description from whatever property names exist
        title = ""
        description = ""
        for key, val in task.items():
            if key in ("Task Name", "Name", "Title") and val:
                title = val
            if key in ("Description",) and val:
                description = val
        if not title:
            title = str(page_id)[:20]

        self.db.log("worker", "task_claimed", title, page_id)

        # Semantic memory recall before execution
        recall_text = description or title
        recalled = self.memory.recall(self.db, "worker", recall_text, top_k=5)
        if recalled:
            print(f"  Worker: Recalled {len(recalled)} relevant memories for '{title}'")
            for m in recalled[:3]:
                print(f"    - [{m['category']}] {m['content'][:80]}")

        print(f"  Worker: Executing task '{title}'")

        # Execute — the Agent gets page_id in its context so it can use notion_update
        result = self._execute_task(task, title, description)

        self.db.log("worker", "task_done", result[:100], page_id)
        print(f"  Worker: Task '{title}' finished: {result[:80]}")
        self._learn_from_task(title, page_id, result)

    def _execute_task(self, task: dict, title: str, description: str) -> str:
        """Execute the task using the browser agent."""
        from macgent.agent import Agent

        page_id = task["page_id"]

        # Build task text with page_id so the agent can update Notion
        task_text = description or title
        task_context = (
            f"{task_text}\n\n"
            f"[Your Notion task page_id: {page_id}]\n"
            f"Use notion_update with this page_id to update your progress and status."
        )

        agent = Agent(
            self.config, db=self.db, task_id=page_id,
            memory=self.memory, task_description=task_text,
        )
        state = agent.run(task_context)

        parts = [f"Status: {state.status}", f"Steps: {len(state.steps)}"]
        if state.steps:
            last = state.steps[-1]
            if last.action.type == "done":
                parts.append(f"Summary: {last.action.params.get('summary', 'completed')}")
            elif last.action_result:
                parts.append(f"Last result: {last.action_result[:200]}")

        return "\n".join(parts)

    def _learn_from_task(self, title: str, page_id: str, result: str):
        """Extract and store a lesson from the completed task."""
        system = self.get_system_prompt()
        prompt = WORKER_LEARN_PROMPT.format(
            task_title=title,
            result=result[:500],
            steps="(see above)",
        )
        try:
            response = self.call_llm(
                [{"role": "user", "content": prompt}],
                system=system, max_tokens=256,
            )
            data = self.parse_json(response)
            if data and "lesson" in data:
                self.memory.remember(
                    self.db, "worker", data["lesson"],
                    category=data.get("category", "lesson"),
                    task_id=page_id,
                )
                print(f"  Worker: Learned — {data['lesson'][:60]}")
        except Exception as e:
            logger.debug(f"Learning failed (non-critical): {e}")
