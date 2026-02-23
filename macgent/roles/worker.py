"""Worker role — executes tasks and updates Notion board."""

import logging
from macgent.roles.base import BaseRole
from macgent.prompts.role_prompts import WORKER_LEARN_PROMPT
from macgent.actions import notion_actions

logger = logging.getLogger("macgent.roles.worker")


def _notify_task_update(config, db, task_id: int):
    """Send Telegram notification for task update (non-blocking)."""
    try:
        from macgent.telegram_bot import sync_notify_task_update
        sync_notify_task_update(config, db, task_id)
    except Exception as e:
        logger.debug(f"Failed to send Telegram notification: {e}")


class WorkerRole(BaseRole):
    role_name = "worker"

    def tick(self):
        """Called each heartbeat: check messages, claim and run next task."""
        logger.info("Worker tick starting")
        self.db.log("worker", "tick_start")

        # Check for manager pings
        pings = self.db.get_unread_messages("worker")
        for msg in pings:
            if msg["from_role"] == "manager":
                print(f"  Worker: Got ping from Manager: {msg['content'][:80]}")
        self.db.mark_messages_read("worker")

        # Pick next pending task
        task = self.db.next_pending_task()
        if not task:
            print("  Worker: No pending tasks")
            self.db.log("worker", "no_tasks")
            return

        print(f"  Worker: Claiming task #{task['id']}: {task['title']}")
        self.run_task(task["id"])

        self.db.log("worker", "tick_done")

    def run_task(self, task_id: int):
        """Execute a task: claim → execute → update Notion → learn."""
        task = self.db.get_task(task_id)
        if not task:
            logger.error(f"Task #{task_id} not found")
            return

        self.db.log("worker", "task_claimed", task["title"], task_id)

        # Mark in progress (SQLite + Notion)
        self.db.update_task(task_id, status="in_progress")
        self._update_notion(task, "In Progress")
        print(f"  Worker: Executing task #{task_id}: {task['title']}")

        # Execute
        result = self._execute_task(task)
        success = "status: completed" in result.lower()

        db_status = "completed" if success else "failed"
        notion_status = "Done" if success else "Failed"

        self.db.update_task(task_id, result=result, status=db_status)
        # Re-fetch to get latest notion_page_id
        self._update_notion(self.db.get_task(task_id), notion_status, note=result[:500])
        self.db.log("worker", db_status, result[:100], task_id)

        print(f"  Worker: Task #{task_id} {db_status}: {result[:80]}")
        _notify_task_update(self.config, self.db, task_id)
        self._learn_from_task(task, result)

    def _update_notion(self, task: dict, status: str, note: str = ""):
        """Update task status in Notion if a page_id is linked."""
        if not task:
            return
        page_id = task.get("notion_page_id")
        if not page_id or not self.config.notion_token:
            return
        notion_actions.update_task(
            self.config.notion_token,
            page_id,
            status=status,
            note=note or None,
        )

    def _execute_task(self, task: dict) -> str:
        """Execute the task using the browser agent."""
        from macgent.agent import Agent

        agent = Agent(self.config, db=self.db, task_id=task["id"])
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
                    task_id=task.get("id"),
                )
                print(f"  Worker: Learned — {data['lesson'][:60]}")
        except Exception as e:
            logger.debug(f"Learning failed (non-critical): {e}")
