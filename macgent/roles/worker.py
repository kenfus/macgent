"""Minimal worker role: claim ready Notion tasks and execute with Agent."""

from __future__ import annotations

import logging

from macgent.actions.dispatcher import set_dispatch_config
from macgent.roles.base import BaseRole

logger = logging.getLogger("macgent.roles.worker")


class WorkerRole(BaseRole):
    role_name = "worker"

    def __init__(self, config, db, memory):
        super().__init__(config, db, memory)
        set_dispatch_config(config)

    def tick(self):
        from macgent.actions import notion_actions

        tasks = notion_actions.notion_query(self.config.notion_token, self.config.notion_database_id)
        if not tasks:
            return

        ready = None
        for t in tasks:
            status = str(t.get("Status", "")).lower()
            if "ready" in status and "not" not in status:
                ready = t
                break

        if ready:
            self.run_task(ready)

    def run_task(self, task: dict):
        from macgent.agent import Agent

        page_id = task["page_id"]
        title = task.get("Task Name") or task.get("Name") or task.get("Title") or str(page_id)[:20]
        description = task.get("Description", "") or title

        task_context = (
            f"{description}\n\n"
            f"[Your Notion task page_id: {page_id}]\n"
            "Use notion_update with this page_id to report progress/status."
        )

        agent = Agent(self.config, db=self.db, task_id=page_id, memory=self.memory, task_description=description)
        state = agent.run(task_context)

        logger.info("Worker finished page_id=%s status=%s steps=%s", page_id, state.status, len(state.steps))
