"""Worker role — executes tasks from Notion board and updates progress there.

The Worker NEVER messages the CEO directly. All communication goes through
the Notion board. The Manager reads it and talks to the CEO.
"""

import logging
from macgent.roles.base import BaseRole
from macgent.prompts.role_prompts import WORKER_LEARN_PROMPT
from macgent.actions import notion_actions
from macgent.actions.dispatcher import set_notion_context

logger = logging.getLogger("macgent.roles.worker")


class WorkerRole(BaseRole):
    role_name = "worker"

    @property
    def _token(self):
        return self.config.notion_token

    @property
    def _db_id(self):
        return self.config.notion_database_id

    def tick(self):
        """Called each heartbeat: claim and run next Ready task from Notion."""
        logger.info("Worker tick starting")
        self.db.log("worker", "tick_start")

        task = notion_actions.next_ready_task(self._token, self._db_id)
        if not task:
            print("  Worker: No ready tasks")
            self.db.log("worker", "no_tasks")
            return

        print(f"  Worker: Claiming task '{task['title']}'")
        self.run_task(task)

        self.db.log("worker", "tick_done")

    def run_task(self, task: dict):
        """Execute a Notion task: claim → execute → update Notion → learn.

        Args:
            task: Notion task dict with at least page_id, title, description.
        """
        page_id = task["page_id"]
        self.db.log("worker", "task_claimed", task["title"], page_id)

        # Set Notion context so the agent's notion_update action works
        set_notion_context(self._token, page_id)

        # Semantic memory recall before execution
        recalled = self.memory.recall(self.db, "worker", task["description"], top_k=5)
        if recalled:
            print(f"  Worker: Recalled {len(recalled)} relevant memories for '{task['title']}'")
            for m in recalled[:3]:
                print(f"    - [{m['category']}] {m['content'][:80]}")

        # Mark In Progress in Notion
        notion_actions.update_task(self._token, page_id, status="In Progress")
        print(f"  Worker: Executing task '{task['title']}'")

        # Execute
        result = self._execute_task(task)

        # Done or Blocked — worker never sends Telegram, only updates Notion
        success = "status: completed" in result.lower()
        if success:
            notion_actions.update_task(
                self._token, page_id,
                status="Done", note=result[:500],
            )
            self.db.log("worker", "completed", result[:100], page_id)
        else:
            notion_actions.update_task(
                self._token, page_id,
                status="Blocked", note=result[:500],
            )
            self.db.log("worker", "blocked", result[:100], page_id)

        print(f"  Worker: Task '{task['title']}' → {'Done' if success else 'Blocked'}: {result[:80]}")
        self._learn_from_task(task, result)

    def _execute_task(self, task: dict) -> str:
        """Execute the task using the browser agent."""
        from macgent.agent import Agent

        agent = Agent(
            self.config, db=self.db, task_id=task["page_id"],
            memory=self.memory, task_description=task["description"],
        )
        state = agent.run(task["description"])

        parts = [f"Status: {state.status}", f"Steps: {len(state.steps)}"]
        if state.steps:
            last = state.steps[-1]
            if last.action.type == "done":
                parts.append(f"Summary: {last.action.params.get('summary', 'completed')}")
            elif last.action_result:
                parts.append(f"Last result: {last.action_result[:200]}")

        return "\n".join(parts)

    def _learn_from_task(self, task: dict, result: str):
        """Extract and store a lesson from the completed task."""
        system = self.get_system_prompt()
        prompt = WORKER_LEARN_PROMPT.format(
            task_title=task["title"],
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
                    task_id=task.get("page_id"),
                )
                print(f"  Worker: Learned — {data['lesson'][:60]}")
        except Exception as e:
            logger.debug(f"Learning failed (non-critical): {e}")
