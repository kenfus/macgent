"""Minimal LLM-driven manager.

All heartbeat decisions come from markdown instructions in workspace files.
Python only provides context, executes returned actions, and handles loop control.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from macgent.actions.dispatcher import dispatch, set_dispatch_config
from macgent.models import Action
from macgent.roles.base import BaseRole

logger = logging.getLogger("macgent.roles.manager")
MAX_TURNS = 15


class ManagerRole(BaseRole):
    role_name = "manager"

    def __init__(self, config, db, memory):
        super().__init__(config, db, memory)
        set_dispatch_config(config)

    def _is_bootstrapped(self) -> bool:
        base = Path(self.config.workspace_dir) / "manager"
        return (base / "identity.md").exists() or (base / "IDENTITY.md").exists()

    def should_wake_early(self) -> bool:
        row = self.db.conn.execute(
            "SELECT metadata FROM monitor_state WHERE source = ?",
            ("_wake_request",),
        ).fetchone()
        return bool(row)

    def clear_wake_request(self):
        self.db.conn.execute("DELETE FROM monitor_state WHERE source = ?", ("_wake_request",))
        self.db.conn.commit()

    def _load_manager_task_prompt(self) -> str:
        manager_dir = Path(self.config.workspace_dir) / "manager"
        if not self._is_bootstrapped():
            p = manager_dir / "bootstrap.md"
            if p.exists():
                return p.read_text()
            return "Bootstrap missing. Create manager/identity.md, then continue with heartbeat."

        p = manager_dir / "heartbeat.md"
        if p.exists():
            return p.read_text()
        return "Run manager heartbeat based on current board/messages and respond HEARTBEAT_OK if nothing to do."

    def tick(self) -> bool:
        logger.info("Manager tick starting")

        if self.should_wake_early():
            self.clear_wake_request()

        system = self.get_system_prompt()
        prompt = self._load_manager_task_prompt()

        # Feed unread CEO messages as context; LLM decides what to do.
        ceo_messages = self.db.get_unread_messages("manager")
        ceo_texts = [m["content"] for m in ceo_messages if m.get("from_role") == "ceo"]
        if ceo_messages:
            self.db.mark_messages_read("manager")

        if ceo_texts:
            prompt += "\n\n## CEO Messages\n"
            for i, t in enumerate(ceo_texts, 1):
                prompt += f"\n{i}. {t}\n"

        conversation = [{"role": "user", "content": prompt}]
        did_work = False

        for _ in range(MAX_TURNS):
            try:
                response = self.call_llm(conversation, system=system, max_tokens=2048)
            except Exception as e:
                logger.error("Manager LLM call failed: %s", e)
                break

            if "HEARTBEAT_OK" in response:
                return did_work

            data = self.parse_json(response)
            if not data:
                logger.debug("Manager returned non-JSON; stopping tick")
                break

            actions = data.get("actions", [])
            if not actions and "action" in data:
                actions = [data["action"]]
            if not actions and "type" in data:
                actions = [data]

            if not actions:
                break

            results = []
            for a in actions:
                a_type = a.get("type", "")
                params = a.get("params", {})
                result = self._execute_action(a_type, params)
                results.append(f"[{a_type}] {result}")
                did_work = True

            conversation.append({"role": "assistant", "content": response})
            conversation.append(
                {
                    "role": "user",
                    "content": "Action results:\n" + "\n".join(results) + "\n\nContinue or respond HEARTBEAT_OK.",
                }
            )

        return did_work

    def handle_new_ceo_task(self, task_text: str) -> str | None:
        """Ask manager LLM to create a Notion task from a direct CLI request."""
        system = self.get_system_prompt(task_description=task_text)
        prompt = (
            "Create a Notion task from this CEO request. "
            "Use notion_create and include clear title/description/priority fields based on board schema.\n\n"
            f"CEO request: {task_text}"
        )
        conversation = [{"role": "user", "content": prompt}]

        for _ in range(6):
            try:
                response = self.call_llm(conversation, system=system, max_tokens=2048)
            except Exception as e:
                logger.error("Manager LLM call failed: %s", e)
                return None

            data = self.parse_json(response)
            if not data:
                return None

            actions = data.get("actions", [])
            if not actions and "action" in data:
                actions = [data["action"]]
            if not actions and "type" in data:
                actions = [data]

            if not actions:
                return None

            results = []
            for a in actions:
                a_type = a.get("type", "")
                params = a.get("params", {})
                out = self._execute_action(a_type, params)
                results.append(f"[{a_type}] {out}")

                if a_type == "notion_create" and "page_id" in out:
                    try:
                        return json.loads(out).get("page_id")
                    except Exception:
                        pass

            conversation.append({"role": "assistant", "content": response})
            conversation.append({"role": "user", "content": "Results:\n" + "\n".join(results)})

        return None

    def _execute_action(self, action_type: str, params: dict) -> str:
        if action_type == "send_telegram":
            text = params.get("text", params.get("message", ""))
            if not text:
                return "ERROR: send_telegram needs 'text'"
            try:
                from macgent.telegram_bot import sync_send_message

                sync_send_message(self.config, text)
                return f"Telegram sent: {text[:120]}"
            except Exception as e:
                return f"ERROR: send_telegram failed: {e}"

        if action_type == "start_worker":
            return "Worker start queued"

        try:
            return dispatch(Action(type=action_type, params=params, reasoning="manager action"))
        except Exception as e:
            return f"ERROR: {e}"
