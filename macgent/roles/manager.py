"""Minimal LLM-driven manager.

All heartbeat decisions come from markdown instructions in workspace files.
Python only provides context, executes returned actions, and handles loop control.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import re
from pathlib import Path

from macgent.actions.dispatcher import dispatch, set_dispatch_config, set_last_ceo_message
from macgent import message_bus
from macgent.models import Action
from macgent.roles.base import BaseRole
from macgent.pulse import STATE_RELATIVE_PATH

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

    @staticmethod
    def _extract_pulse_task_id(content: str) -> str | None:
        """Parse [task_id=X] marker injected by the pulse into system messages."""
        m = re.match(r"\[task_id=([^\]]+)\]", content or "")
        return m.group(1) if m else None

    def _update_pulse_state(self, task_id: str, status: str) -> None:
        """Write task completion status back to PULSE_STATE.json."""
        state_path = Path(self.config.workspace_dir) / STATE_RELATIVE_PATH
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            state: dict = {}
            if state_path.exists():
                state = json.loads(state_path.read_text())
            state.setdefault("tasks", {}).setdefault(task_id, {}).update(
                {"status": status, "updated_at": now_str}
            )
            state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.warning("Manager: could not update pulse state for '%s': %s", task_id, e)

    def _build_ceo_prompt_content(self, base_text: str, incoming_message: dict) -> str | list[dict]:
        """Build a multimodal user message when CEO attachments include images."""
        attachments = incoming_message.get("attachments") or []
        image_attachments = [a for a in attachments if isinstance(a, dict) and a.get("type") == "image"]
        if not image_attachments:
            return base_text

        content: list[dict] = [{"type": "text", "text": base_text}]
        workspace = Path(self.config.workspace_dir)
        max_images = 3
        loaded = 0
        notes: list[str] = []

        for att in image_attachments[:max_images]:
            rel = str(att.get("path", "")).strip()
            if not rel:
                continue
            media_type = str(att.get("media_type", "image/jpeg")).strip() or "image/jpeg"
            abs_path = (workspace / rel).resolve()
            try:
                payload = base64.b64encode(abs_path.read_bytes()).decode("ascii")
            except Exception as e:
                notes.append(f"- could not read attachment `{rel}` ({e})")
                continue
            content.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{payload}"}})
            loaded += 1

        if len(image_attachments) > max_images:
            notes.append(f"- omitted {len(image_attachments) - max_images} additional image attachment(s)")
        if notes:
            content[0]["text"] = base_text + "\n\n## Attachment Notes\n" + "\n".join(notes) + "\n"
        if loaded == 0:
            return content[0]["text"]
        return content

    @staticmethod
    def _attachment_update_suffix(message: dict) -> str:
        attachments = message.get("attachments") or []
        images = [a for a in attachments if isinstance(a, dict) and a.get("type") == "image"]
        if not images:
            return ""
        paths = [str(a.get("path", "")).strip() for a in images[:2] if str(a.get("path", "")).strip()]
        path_preview = f" ({', '.join(paths)})" if paths else ""
        extra = len(images) - len(paths)
        extra_suffix = f", +{extra} more" if extra > 0 else ""
        return f"\n[Includes {len(images)} image attachment(s){path_preview}{extra_suffix}]"

    def tick(self) -> bool:
        logger.info("Manager tick starting")
        bootstrapped = self._is_bootstrapped()

        is_active_wake = self.should_wake_early()
        if is_active_wake:
            self.clear_wake_request()

        # Dequeue the next incoming message on active wake.
        # CEO messages (from Telegram) take priority over system messages (from pulse).
        incoming_message = None
        incoming_from = None
        system_task_id: str | None = None  # pulse task ID, for completion tracking
        if is_active_wake:
            msg = message_bus.dequeue_message("agent", from_role="ceo")
            if msg:
                incoming_message, incoming_from = msg, "ceo"
            else:
                msg = message_bus.dequeue_message("agent", from_role="system")
                if msg:
                    incoming_message, incoming_from = msg, "system"
                    system_task_id = self._extract_pulse_task_id(msg.get("content", ""))

            if incoming_message:
                logger.info(
                    "Manager loaded message (id=%s, from=%s)",
                    incoming_message.get("id"), incoming_from,
                )
                # Only CEO messages go into daily memory (system tasks are maintenance noise)
                if incoming_from == "ceo":
                    ts = datetime.datetime.now().strftime("%H:%M")
                    attachment_note = self._attachment_update_suffix(incoming_message)
                    self.memory.append_to_daily_memory(
                        f"**[{ts}] CEO:**\n{incoming_message['content']}{attachment_note}\n"
                    )
                # Re-signal if more messages are waiting
                if message_bus.has_pending_messages("agent", from_role="ceo") or \
                        message_bus.has_pending_messages("agent", from_role="system"):
                    message_bus.request_wake()
                    logger.info("More messages pending — re-signalling wake")
            else:
                logger.info("Active wake received but no queued message found")

        # All modes share the same full context (soul + skills + memory).
        # Only the user prompt differs: BOOTSTRAP.md, HEARTBEAT.md, or an incoming message.
        system = self.get_system_prompt()
        prompt_content: str | list[dict]
        if not bootstrapped:
            prompt = self._load_manager_task_prompt()
            if incoming_message:
                label = "CEO Reply" if incoming_from == "ceo" else "System Task"
                base_text = prompt + f"\n\n## {label}\n\n{incoming_message['content']}\n"
                if incoming_from == "ceo":
                    prompt_content = self._build_ceo_prompt_content(base_text, incoming_message)
                else:
                    prompt_content = base_text
            else:
                prompt_content = prompt
        else:
            if incoming_message:
                if incoming_from == "ceo":
                    base_text = (
                        "Process this CEO message now. Execute actions as needed. "
                        'When fully handled, finish with {"type": "finish"}.\n\n'
                        "## CEO Message\n\n"
                        f"{incoming_message['content']}\n"
                    )
                    prompt_content = self._build_ceo_prompt_content(base_text, incoming_message)
                else:
                    # System task (e.g. memory distillation from pulse)
                    prompt_content = (
                        "Process this system task. Execute actions as needed. "
                        'When fully handled, finish with {"type": "finish"}.\n\n'
                        f"{incoming_message['content']}\n"
                    )
            else:
                prompt_content = self._load_manager_task_prompt()

        conversation = [{"role": "user", "content": prompt_content}]
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
                if system_task_id:
                    self._update_pulse_state(system_task_id, "completed")
                return did_work

            # Break only if no actions AND no explicit continue signal
            if not actions and not is_continue:
                break

            conversation.append({"role": "assistant", "content": response})

            user_content = "Action results:\n" + "\n".join(results)

            # Check for a new CEO message that arrived mid-task and inject it.
            mid_task_msg = message_bus.dequeue_message("agent", from_role="ceo")
            if mid_task_msg:
                set_last_ceo_message(mid_task_msg["content"], mid_task_msg.get("attachments"))
                attachment_suffix = self._attachment_update_suffix(mid_task_msg)
                user_content += (
                    f"\n\n[UPDATE FROM VINCENZO]: {mid_task_msg['content']}{attachment_suffix}\n"
                    "Incorporate if relevant, or call re_queue_message (no params needed) to defer."
                )

            conversation.append({"role": "user", "content": user_content + "\n\nContinue."})

        # Loop exited without a finish signal — record timeout for pulse tasks
        if system_task_id:
            self._update_pulse_state(system_task_id, "timeout")
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
