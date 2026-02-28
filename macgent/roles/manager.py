"""Minimal LLM-driven manager.

All heartbeat decisions come from markdown instructions in workspace files.
Python only provides context, executes returned actions, and handles loop control.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from macgent.actions.dispatcher import dispatch, set_dispatch_config
from macgent import message_bus
from macgent.models import Action
from macgent.roles.base import BaseRole

logger = logging.getLogger("macgent.roles.manager")
MAX_TURNS = 15


class ManagerRole(BaseRole):
    role_name = "agent"

    def __init__(self, config, db, memory):
        super().__init__(config, db, memory)
        set_dispatch_config(config)

    def _is_bootstrapped(self) -> bool:
        base = Path(self.config.workspace_dir) / "agent"
        has_identity = (base / "IDENTITY.md").exists() or (base / "identity.md").exists()
        # Bootstrap is complete only after IDENTITY exists AND BOOTSTRAP has been removed.
        return has_identity and not (base / "BOOTSTRAP.md").exists()

    def should_wake_early(self) -> bool:
        return message_bus.should_wake()

    def clear_wake_request(self):
        message_bus.clear_wake()

    def _load_manager_task_prompt(self) -> str:
        manager_dir = Path(self.config.workspace_dir) / "agent"
        if not self._is_bootstrapped():
            p = manager_dir / "BOOTSTRAP.md"
            if p.exists():
                return p.read_text()
            return "Bootstrap missing. Create agent/IDENTITY.md, then continue with heartbeat."

        p = manager_dir / "HEARTBEAT.md"
        if p.exists():
            return p.read_text()
        return "Run manager heartbeat based on current board/messages and respond HEARTBEAT_OK if nothing to do."

    def tick(self) -> bool:
        logger.info("Manager tick starting")
        bootstrapped = self._is_bootstrapped()

        is_active_wake = self.should_wake_early()
        if is_active_wake:
            self.clear_wake_request()

        ceo_message = None
        # Only active wake cycles consume Telegram queue messages.
        if is_active_wake and bootstrapped:
            ceo_message = message_bus.dequeue_message("agent", from_role="ceo")
            if ceo_message:
                logger.info("Manager loaded 1 CEO message from queue (id=%s)", ceo_message.get("id"))
            else:
                logger.info("Active wake received but no queued CEO message found")
        elif is_active_wake and not bootstrapped:
            logger.info("Active wake ignored during bootstrap-only mode")

        # First boot is bootstrap-only: SOUL + BOOTSTRAP, no extra memory/skills context.
        if not bootstrapped:
            system = self.memory.load_soul("agent")
            prompt = self._load_manager_task_prompt()
        else:
            system = self.get_system_prompt()
            if ceo_message:
                prompt = (
                    "Process this CEO message now. Execute actions as needed. "
                    "When fully handled, respond HEARTBEAT_OK.\n\n"
                    "## CEO Message\n\n"
                    f"{ceo_message['content']}\n"
                )
            else:
                prompt = self._load_manager_task_prompt()

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
