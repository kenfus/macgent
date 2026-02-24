"""Manager role — LLM-driven heartbeat with generic action dispatch.

The Manager is an agent loop: Python assembles context (soul + skills + memory),
LLM decides what actions to take (query Notion, send Telegram, create tasks),
Python executes them and feeds results back. Loop until HEARTBEAT_OK or max turns.
"""

import json
import logging
from pathlib import Path

from macgent.roles.base import BaseRole
from macgent.actions.dispatcher import set_dispatch_config
from macgent.monitors.email_monitor import EmailMonitor

logger = logging.getLogger("macgent.roles.manager")

MAX_TURNS = 15


def _send_telegram(config, text: str):
    """Non-blocking Telegram message to CEO."""
    try:
        from macgent.telegram_bot import sync_send_message
        sync_send_message(config, text)
    except Exception as e:
        logger.debug(f"Telegram send failed: {e}")


class ManagerRole(BaseRole):
    role_name = "manager"

    def __init__(self, config, db, memory):
        super().__init__(config, db, memory)
        self.monitors = [EmailMonitor()]
        # Push config to dispatcher so Notion actions have token/db_id
        set_dispatch_config(config)

    def _is_bootstrapped(self) -> bool:
        """Check if bootstrap has been completed (IDENTITY.md exists)."""
        identity_path = Path(self.config.workspace_dir) / "manager" / "IDENTITY.md"
        return identity_path.exists()

    def should_wake_early(self) -> bool:
        row = self.db.conn.execute(
            "SELECT metadata FROM monitor_state WHERE source = ?",
            ("_wake_request",)
        ).fetchone()
        return bool(row)

    def clear_wake_request(self):
        self.db.conn.execute("DELETE FROM monitor_state WHERE source = ?", ("_wake_request",))
        self.db.conn.commit()

    def _cleanup_bootstrap(self):
        """Delete bootstrap.md after bootstrap completes (IDENTITY.md exists)."""
        bootstrap_path = Path(self.config.workspace_dir) / "manager" / "bootstrap.md"
        if bootstrap_path.exists():
            bootstrap_path.unlink()
            logger.info("Bootstrap complete — deleted manager/bootstrap.md")

    def tick(self) -> bool:
        """One heartbeat cycle. Returns True if something happened."""
        logger.info("Manager tick starting")

        woken_early = self.should_wake_early()
        if woken_early:
            logger.info("Manager woken by external notification")
            self.clear_wake_request()

        was_bootstrapped = self._is_bootstrapped()

        # 1. Build full context (Python does this automatically)
        #    soul.md + IDENTITY.md + all skills + MEMORY.md + daily logs + FAISS recall
        system = self.get_system_prompt()

        # 2. Gather structured input
        ceo_messages = self.db.get_unread_messages("manager")
        ceo_texts = []
        for msg in ceo_messages:
            if msg["from_role"] == "ceo":
                ceo_texts.append(msg["content"])
        if ceo_messages:
            self.db.mark_messages_read("manager")

        # Check email monitors (skip during bootstrap — first boot is setup only)
        email_items = []
        if was_bootstrapped:
            for monitor in self.monitors:
                try:
                    items = monitor.check(self.db)
                    email_items.extend(items)
                except Exception as e:
                    logger.error(f"Monitor {monitor.source_name} failed: {e}")

        # 3. Build the task prompt
        if not was_bootstrapped:
            # First time: load bootstrap instructions
            bootstrap_path = Path(self.config.workspace_dir) / "manager" / "bootstrap.md"
            if bootstrap_path.exists():
                task_prompt = bootstrap_path.read_text()
            else:
                task_prompt = "No bootstrap.md found. Set yourself up: write IDENTITY.md and user.md, then introduce yourself via Telegram."
            # Include any queued CEO messages as context (e.g. from Telegram before first boot)
            if ceo_texts:
                task_prompt += "\n\n## CEO Messages (context — what they've already written to you)\n"
                for i, text in enumerate(ceo_texts, 1):
                    task_prompt += f"\n{i}. {text}\n"
            logger.info("Manager running bootstrap (no IDENTITY.md found)")
        else:
            # Normal heartbeat
            heartbeat_path = Path(self.config.workspace_dir) / "manager" / "heartbeat.md"
            task_prompt = heartbeat_path.read_text() if heartbeat_path.exists() else "Run heartbeat checks."

            # Add CEO messages
            if ceo_texts:
                task_prompt += "\n\n## CEO Messages (just arrived)\n"
                for i, text in enumerate(ceo_texts, 1):
                    task_prompt += f"\n{i}. {text}\n"

            # Add email notifications
            if email_items:
                task_prompt += "\n\n## New Emails\n"
                for item in email_items:
                    task_prompt += f"\n- From: {item.get('from', '?')} | Subject: {item.get('subject', '?')}\n"

            # Add wake info
            if woken_early:
                task_prompt += "\n\n(You were woken early by an external notification — likely a new CEO message.)\n"

        # 4. Agent loop: LLM decides actions, Python executes them
        conversation = [{"role": "user", "content": task_prompt}]
        anything_happened = False

        # Bootstrap needs more tokens to write large files (skills/notion.md, IDENTITY.md)
        tick_max_tokens = 4096 if not self._is_bootstrapped() else 2048

        for turn in range(MAX_TURNS):
            try:
                response = self.call_llm(conversation, system=system, max_tokens=tick_max_tokens)
            except Exception as e:
                logger.error(f"Manager LLM call failed: {e}")
                break

            logger.debug(f"Manager turn {turn}: {response[:200]}")

            # Check for HEARTBEAT_OK
            if "HEARTBEAT_OK" in response:
                if not anything_happened:
                    print("HEARTBEAT_OK")
                    logger.debug("Manager tick: HEARTBEAT_OK (nothing to do)")
                else:
                    logger.info("Manager tick done (actions taken)")
                return anything_happened

            # Parse actions from response
            data = self.parse_json(response)
            if not data:
                # LLM returned plain text — treat as done
                logger.debug(f"Manager returned non-JSON: {response[:100]}")
                break

            # Execute actions
            actions = data.get("actions", [])
            if not actions and "action" in data:
                actions = [data["action"]]
            if not actions:
                # Single action without wrapper
                if "type" in data:
                    actions = [data]

            results = []
            for action_dict in actions:
                action_type = action_dict.get("type", "")
                params = action_dict.get("params", {})
                result = self._execute_action(action_type, params)
                results.append(f"[{action_type}] {result}")
                anything_happened = True

                # Log significant actions
                if action_type in ("notion_create", "notion_update", "send_telegram", "write_file", "delete_file"):
                    logger.info(f"Manager action: {action_type} params={str(params)[:200]}")

            # Feed results back to LLM
            result_text = "\n".join(results) if results else "(no actions executed)"
            conversation.append({"role": "assistant", "content": response})
            conversation.append({"role": "user", "content": f"Action results:\n{result_text}\n\nContinue with next step, or respond HEARTBEAT_OK if done."})

        # If bootstrap just completed, clean up bootstrap.md (Python handles it even if LLM forgot)
        if not was_bootstrapped and self._is_bootstrapped():
            self._cleanup_bootstrap()

        # Max turns reached or LLM stopped
        if anything_happened:
            self.memory.write_daily_log(self.db, "Heartbeat completed with actions.")
            logger.info("Manager tick done (max turns or LLM stopped)")
        else:
            print("HEARTBEAT_OK")
            logger.debug("Manager tick: HEARTBEAT_OK (max turns, nothing happened)")
        return anything_happened

    def handle_new_ceo_task(self, task_text: str) -> str | None:
        """Process a new task from CEO (via CLI). Returns page_id or None.

        This is a simplified path for `macgent task '...'` — goes through the
        LLM agent loop with a specific task creation prompt.
        """
        system = self.get_system_prompt()
        prompt = (
            f"The CEO just gave you a new task via command line:\n\n"
            f'"{task_text}"\n\n'
            f"Process it: enhance the description, decide priority, and create it on the Notion board. "
            f"If you need clarification, create it with backlog/inbox status and note the question. "
            f"Use notion_create to add it to the board. "
            f"Respond with the action to create the task."
        )

        conversation = [{"role": "user", "content": prompt}]
        page_id = None

        for turn in range(5):
            try:
                response = self.call_llm(conversation, system=system, max_tokens=2048)
            except Exception as e:
                logger.error(f"Manager LLM call failed: {e}")
                break

            data = self.parse_json(response)
            if not data:
                break

            actions = data.get("actions", [])
            if not actions and "action" in data:
                actions = [data["action"]]
            if not actions and "type" in data:
                actions = [data]

            results = []
            for action_dict in actions:
                action_type = action_dict.get("type", "")
                params = action_dict.get("params", {})
                result = self._execute_action(action_type, params)
                results.append(f"[{action_type}] {result}")

                # Capture page_id from notion_create
                if action_type == "notion_create" and "page_id" in result:
                    try:
                        result_data = json.loads(result)
                        page_id = result_data.get("page_id")
                    except (json.JSONDecodeError, TypeError):
                        pass

            if page_id:
                logger.info(f"Manager created task: {task_text[:100]} (page_id={page_id})")
                self.memory.write_daily_log(self.db, f"Created task from CLI: {task_text[:80]}")
                break

            conversation.append({"role": "assistant", "content": response})
            result_text = "\n".join(results)
            conversation.append({"role": "user", "content": f"Results:\n{result_text}\n\nDone? If task was created, you can stop."})

        return page_id

    def _execute_action(self, action_type: str, params: dict) -> str:
        """Execute a single action. Handles both dispatcher actions and manager-specific ones."""
        from macgent.actions.dispatcher import dispatch
        from macgent.models import Action

        # Manager-specific: send_telegram
        if action_type == "send_telegram":
            text = params.get("text", params.get("message", ""))
            if text:
                _send_telegram(self.config, text)
                return f"Telegram sent: {text[:80]}"
            return "ERROR: send_telegram needs 'text'"

        # Manager-specific: start_worker (signals that a task should be run)
        if action_type == "start_worker":
            # This is handled by the daemon loop, not directly here
            return "Worker start queued (daemon will pick it up)"

        # All other actions go through dispatcher
        try:
            action = Action(type=action_type, params=params, reasoning="manager action")
            return dispatch(action)
        except Exception as e:
            return f"ERROR: {e}"
