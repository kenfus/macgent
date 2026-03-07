"""Agent daemon — heartbeat loop that drives the agent tick by tick.

Wakes on:
- Schedule (every daemon_interval seconds, default 30 min)
- Telegram message (early wake via message_bus)
- Pulse-scheduled task (e.g. memory distillation at 04:01)
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Iterable

from macgent.actions.dispatcher import dispatch, set_dispatch_config, set_last_ceo_message
from macgent import message_bus
from macgent.models import Action
from macgent.pulse import STATE_RELATIVE_PATH
from macgent.reasoning.llm_client import build_text_fallback_client

logger = logging.getLogger("macgent.daemon")
MAX_TURNS = 15


class AgentDaemon:
    def __init__(self, config, db, memory):
        self.config = config
        self.db = db
        self.memory = memory
        self._llm = build_text_fallback_client(config)
        set_dispatch_config(config)

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _call_llm(self, messages: list[dict], system: str = "", max_tokens: int = 2048) -> str:
        content = self._llm.chat(messages=messages, system=system, max_tokens=max_tokens, temperature=0.0)
        if not content or not content.strip():
            raise RuntimeError("LLM returned empty response")
        return content

    def _parse_json(self, text: str) -> dict | None:
        text = text.strip()
        if "<think>" in text:
            parts = text.split("</think>")
            text = parts[-1].strip() if len(parts) > 1 else text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        if "```" in text:
            m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    pass
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None

    def _get_system_prompt(self) -> str:
        return self.memory.build_context(self.db, "agent")

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _is_bootstrapped(self) -> bool:
        base = Path(self.config.workspace_dir) / "agent"
        return (base / "IDENTITY.md").exists() or (base / "identity.md").exists()

    def _load_user_prompt(self) -> str:
        agent_dir = Path(self.config.workspace_dir) / "agent"
        if not self._is_bootstrapped():
            p = agent_dir / "BOOTSTRAP.md"
            return p.read_text() if p.exists() else "Bootstrap missing. Create agent/IDENTITY.md, then continue."
        p = agent_dir / "HEARTBEAT.md"
        return p.read_text() if p.exists() else "Run heartbeat. Respond with heartbeat_ok if nothing to do."

    # ------------------------------------------------------------------
    # Wake / message bus
    # ------------------------------------------------------------------

    def should_wake_early(self) -> bool:
        return message_bus.should_wake()

    def clear_wake_request(self):
        message_bus.clear_wake()

    # ------------------------------------------------------------------
    # Pulse state
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pulse_task_id(content: str) -> str | None:
        m = re.match(r"\[task_id=([^\]]+)\]", content or "")
        return m.group(1) if m else None

    def _update_pulse_state(self, task_id: str, status: str) -> None:
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
            logger.warning("Could not update pulse state for '%s': %s", task_id, e)

    # ------------------------------------------------------------------
    # Multimodal message building
    # ------------------------------------------------------------------

    def _build_user_content(self, base_text: str, message: dict) -> str | list[dict]:
        """Build a multimodal user message when attachments include images."""
        attachments = message.get("attachments") or []
        images = [a for a in attachments if isinstance(a, dict) and a.get("type") == "image"]
        if not images:
            return base_text

        content: list[dict] = [{"type": "text", "text": base_text}]
        workspace = Path(self.config.workspace_dir)
        notes: list[str] = []
        loaded = 0
        for att in images[:3]:
            rel = str(att.get("path", "")).strip()
            if not rel:
                continue
            media_type = str(att.get("media_type", "image/jpeg")).strip() or "image/jpeg"
            try:
                payload = base64.b64encode((workspace / rel).resolve().read_bytes()).decode("ascii")
                content.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{payload}"}})
                loaded += 1
            except Exception as e:
                notes.append(f"- could not read `{rel}` ({e})")
        if len(images) > 3:
            notes.append(f"- omitted {len(images) - 3} additional image(s)")
        if notes:
            content[0]["text"] = base_text + "\n\n## Attachment Notes\n" + "\n".join(notes) + "\n"
        return content if loaded > 0 else content[0]["text"]

    @staticmethod
    def _attachment_suffix(message: dict) -> str:
        images = [a for a in (message.get("attachments") or []) if isinstance(a, dict) and a.get("type") == "image"]
        if not images:
            return ""
        paths = [str(a.get("path", "")).strip() for a in images[:2] if str(a.get("path", "")).strip()]
        extra = len(images) - len(paths)
        return f"\n[Includes {len(images)} image(s){(' (' + ', '.join(paths) + ')') if paths else ''}{(', +' + str(extra) + ' more') if extra else ''}]"

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def tick(self) -> bool:
        logger.info("Agent tick starting")
        bootstrapped = self._is_bootstrapped()

        is_active_wake = self.should_wake_early()
        if is_active_wake:
            self.clear_wake_request()

        incoming_message = None
        incoming_from = None
        system_task_id: str | None = None

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
                logger.info("Loaded message (id=%s, from=%s)", incoming_message.get("id"), incoming_from)
                if incoming_from == "ceo":
                    ts = datetime.datetime.now().strftime("%H:%M")
                    self.memory.append_to_daily_memory(
                        f"**[{ts}] User:**\n{incoming_message['content']}{self._attachment_suffix(incoming_message)}\n"
                    )
                if message_bus.has_pending_messages("agent", from_role="ceo") or \
                        message_bus.has_pending_messages("agent", from_role="system"):
                    message_bus.request_wake()
                    logger.info("More messages pending — re-signalling wake")
            else:
                logger.info("Active wake but no queued message found")

        system = self._get_system_prompt()

        if not bootstrapped:
            prompt = self._load_user_prompt()
            if incoming_message:
                label = "User Reply" if incoming_from == "ceo" else "System Task"
                base_text = prompt + f"\n\n## {label}\n\n{incoming_message['content']}\n"
                prompt_content = self._build_user_content(base_text, incoming_message) if incoming_from == "ceo" else base_text
            else:
                prompt_content = prompt
        else:
            if incoming_message:
                if incoming_from == "ceo":
                    base_text = (
                        "Process this user message now. Execute actions as needed. "
                        'When fully handled, finish with {"type": "finish"}.\n\n'
                        f"## User Message\n\n{incoming_message['content']}\n"
                    )
                    prompt_content = self._build_user_content(base_text, incoming_message)
                else:
                    prompt_content = (
                        "Process this system task. Execute actions as needed. "
                        'When fully handled, finish with {"type": "finish"}.\n\n'
                        f"{incoming_message['content']}\n"
                    )
            else:
                prompt_content = self._load_user_prompt()

        conversation = [{"role": "user", "content": prompt_content}]
        did_work = False

        for _ in range(MAX_TURNS):
            try:
                response = self._call_llm(conversation, system=system)
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                break

            data = self._parse_json(response)
            if not data:
                logger.debug("Non-JSON response; stopping tick")
                break

            is_done = data.get("type") in ("heartbeat_ok", "finish")
            is_continue = data.get("type") == "wait_for_results"

            actions = data.get("actions", [])
            if not actions and "action" in data:
                actions = [data["action"]]
            if not actions and "type" in data and not is_done and not is_continue:
                actions = [data]

            results = []
            for a in actions:
                if not isinstance(a, dict):
                    results.append(f"[skipped] {str(a)[:80]}")
                    continue
                result = self._execute_action(a.get("type", ""), a.get("params", {}))
                results.append(f"[{a.get('type')}] {result}")
                did_work = True

            if is_done:
                if system_task_id:
                    self._update_pulse_state(system_task_id, "completed")
                return did_work

            if not actions and not is_continue:
                break

            conversation.append({"role": "assistant", "content": response})
            user_content = "Action results:\n" + "\n".join(results)

            mid_msg = message_bus.dequeue_message("agent", from_role="ceo")
            if mid_msg:
                set_last_ceo_message(mid_msg["content"], mid_msg.get("attachments"))
                user_content += (
                    f"\n\n[User message received mid-task]: {mid_msg['content']}{self._attachment_suffix(mid_msg)}\n"
                    "Incorporate if relevant, or call re_queue_message to defer."
                )

            conversation.append({"role": "user", "content": user_content + "\n\nContinue."})

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

        try:
            return dispatch(Action(type=action_type, params=params, reasoning="agent action"))
        except Exception as e:
            return f"ERROR: {e}"
