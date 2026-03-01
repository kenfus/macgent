"""Minimal LLM-driven manager.

All heartbeat decisions come from markdown instructions in workspace files.
Python only provides context, executes returned actions, and handles loop control.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from macgent.actions.dispatcher import dispatch, set_dispatch_config, set_last_ceo_message
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
        # IDENTITY.md existing is the only signal that bootstrap completed.
        return (base / "IDENTITY.md").exists() or (base / "identity.md").exists()

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
        return "Run manager heartbeat based on current board/messages and respond with heartbeat_ok if nothing to do."

    def tick(self) -> bool:
        logger.info("Manager tick starting")
        bootstrapped = self._is_bootstrapped()

        is_active_wake = self.should_wake_early()
        if is_active_wake:
            self.clear_wake_request()

        # Dequeue CEO messages on any active wake — including during bootstrap.
        ceo_message = None
        if is_active_wake:
            ceo_message = message_bus.dequeue_message("agent", from_role="ceo")
            if ceo_message:
                logger.info("Manager loaded 1 CEO message from queue (id=%s)", ceo_message.get("id"))
                ts = datetime.datetime.now().strftime("%H:%M")
                self.memory.append_to_daily_memory(f"**[{ts}] CEO:**\n{ceo_message['content']}\n")
                # Re-signal wake if more messages are waiting so the daemon loop
                # processes them immediately instead of waiting for the next heartbeat.
                if message_bus.has_pending_messages("agent", from_role="ceo"):
                    message_bus.request_wake()
                    logger.info("More CEO messages pending — re-signalling wake")
            else:
                logger.info("Active wake received but no queued CEO message found")

        # All modes share the same full context (soul + skills + memory).
        # Only the user prompt differs: BOOTSTRAP.md, HEARTBEAT.md, or a CEO message.
        system = self.get_system_prompt()
        if not bootstrapped:
            prompt = self._load_manager_task_prompt()
            if ceo_message:
                # Append the human's reply so the agent can act on it within bootstrap.
                prompt += f"\n\n## CEO Reply\n\n{ceo_message['content']}\n"
        else:
            if ceo_message:
                prompt = (
                    "Process this CEO message now. Execute actions as needed. "
                    'When fully handled, finish with {"type": "finish"}.\n\n'
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

            data = self.parse_json(response)
            if not data:
                logger.debug("Manager returned non-JSON; stopping tick")
                break

            is_done = data.get("type") in ("heartbeat_ok", "finish")
            is_continue = data.get("type") == "wait_for_results"

            actions = data.get("actions", [])
            if not actions and "action" in data:
                actions = [data["action"]]
            # Only treat the root object as a single action if it isn't a control/continue signal
            if not actions and "type" in data and not is_done and not is_continue:
                actions = [data]

            results = []
            for a in actions:
                if not isinstance(a, dict):
                    results.append(f"[skipped] non-dict action: {str(a)[:80]}")
                    continue
                a_type = a.get("type", "")
                params = a.get("params", {})
                result = self._execute_action(a_type, params)
                results.append(f"[{a_type}] {result}")
                did_work = True

            # If the LLM combined actions + done signal, honour both
            if is_done:
                return did_work

            # Break only if no actions AND no explicit continue signal
            if not actions and not is_continue:
                break

            conversation.append({"role": "assistant", "content": response})

            user_content = "Action results:\n" + "\n".join(results)

            # Check for a new CEO message that arrived mid-task and inject it.
            mid_task_msg = message_bus.dequeue_message("agent", from_role="ceo")
            if mid_task_msg:
                set_last_ceo_message(mid_task_msg["content"])
                user_content += (
                    f"\n\n[UPDATE FROM VINCENZO]: {mid_task_msg['content']}\n"
                    "Incorporate if relevant, or call re_queue_message (no params needed) to defer."
                )

            conversation.append({"role": "user", "content": user_content + "\n\nContinue."})

        return did_work

    def _execute_action(self, action_type: str, params: dict) -> str:
        if action_type == "send_telegram":
            text = params.get("text", params.get("message", ""))
            if not text:
                return "ERROR: send_telegram needs 'text'"
            try:
                from macgent.telegram_bot import sync_send_message

                sync_send_message(self.config, text)
                ts = datetime.datetime.now().strftime("%H:%M")
                self.memory.append_to_daily_memory(f"**[{ts}] Agent:**\n{text}\n")
                return f"Telegram sent: {text[:120]}"
            except Exception as e:
                return f"ERROR: send_telegram failed: {e}"

        if action_type == "start_worker":
            return "Worker start queued"

        try:
            return dispatch(Action(type=action_type, params=params, reasoning="manager action"))
        except Exception as e:
            return f"ERROR: {e}"
