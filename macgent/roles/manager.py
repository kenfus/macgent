"""Manager role — heartbeat monitoring, Notion board, daily memory, task creation.

All task CRUD goes through Notion (notion_actions). SQLite is only used for
messages (CEO reply routing), agent_log, monitor_state, and memory.
"""

import logging
from macgent.roles.base import BaseRole
from macgent.monitors.email_monitor import EmailMonitor
from macgent.prompts.role_prompts import (
    MANAGER_CLASSIFY_PROMPT,
    MANAGER_BOARD_PROMPT,
    MANAGER_ENHANCE_PROMPT,
)
from macgent.actions import notion_actions

logger = logging.getLogger("macgent.roles.manager")


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
        self._notion_ready = False

    @property
    def _token(self):
        return self.config.notion_token

    @property
    def _db_id(self):
        return self.config.notion_database_id

    def _ensure_notion(self):
        """Ensure Notion schema is set up (runs once per session)."""
        if self._notion_ready:
            return
        if self._token and self._db_id:
            notion_actions.ensure_schema(self._token, self._db_id)
            self._notion_ready = True

    def should_wake_early(self) -> bool:
        row = self.db.conn.execute(
            "SELECT metadata FROM monitor_state WHERE source = ?",
            ("_wake_request",)
        ).fetchone()
        return bool(row)

    def clear_wake_request(self):
        self.db.conn.execute("DELETE FROM monitor_state WHERE source = ?", ("_wake_request",))
        self.db.conn.commit()

    def tick(self) -> bool:
        """One heartbeat. Returns True if something actionable happened, False for HEARTBEAT_OK."""
        logger.info("Manager tick starting")
        self.db.log("manager", "tick_start")
        self._ensure_notion()

        woken_early = self.should_wake_early()
        if woken_early:
            logger.info("Manager woken by external notification")
            print("  Manager: Woken by external notification!")
            self.clear_wake_request()

        # 1. Load context: curated memory + recent daily logs are loaded via build_context()
        heartbeat_instructions = self.memory.get_heartbeat_instructions()
        recent_logs = self.memory.get_recent_memory(days=3)
        if recent_logs:
            print(f"  Manager: Loaded {len(recent_logs)} chars of recent memory")

        anything_happened = False

        # 2. Route incoming CEO messages first (so blocked/clarification checks see them)
        if self._handle_ceo_messages():
            anything_happened = True

        # 3. Check clarifications (CEO replied to a pending Inbox question)
        if self._check_pending_clarifications():
            anything_happened = True

        # 4. Check blocked tasks (worker set Blocked, or CEO replied to a blocker)
        if self._check_blocked_tasks():
            anything_happened = True

        # 5. Check notification sources (email etc.)
        all_notifications = []
        for monitor in self.monitors:
            try:
                items = monitor.check(self.db)
                all_notifications.extend(items)
            except Exception as e:
                logger.error(f"Monitor {monitor.source_name} failed: {e}")
                self.db.log("manager", "monitor_error", f"{monitor.source_name}: {e}")

        # 6. Classify and create tasks from notifications
        created = 0
        for notif in all_notifications:
            try:
                page_id = self._classify_and_create(notif)
                if page_id:
                    created += 1
            except Exception as e:
                logger.error(f"Failed to classify notification: {e}")

        if created:
            print(f"  Manager: Created {created} new tasks from notifications")
            anything_happened = True

        # 7. Check stale tasks (re-queue if worker likely died)
        stale_count = self._check_stale_tasks()
        if stale_count:
            anything_happened = True

        # 8. Board health check
        ready = notion_actions.list_tasks(self._token, self._db_id, status="Ready")
        in_progress = notion_actions.list_tasks(self._token, self._db_id, status="In Progress")
        if ready or in_progress:
            anything_happened = True
        board_summary = f"Board: {len(ready)} ready, {len(in_progress)} in progress."

        # HEARTBEAT_OK — nothing actionable this cycle
        if not anything_happened:
            print("HEARTBEAT_OK")
            self.db.log("manager", "tick_done", "HEARTBEAT_OK")
            return False

        # 9. Write daily memory log (only when something happened)
        log_parts = []
        if created:
            log_parts.append(f"Heartbeat: {created} new tasks from email.")
        log_parts.append(board_summary)
        self.memory.write_daily_log(self.db, " ".join(log_parts))

        self.db.log("manager", "tick_done")
        logger.info("Manager tick done")
        return True

    def handle_new_ceo_task(self, task_text: str) -> str | None:
        """Process a new task from CEO (Telegram). Returns page_id or None."""
        self._ensure_notion()
        system = self.get_system_prompt()
        prompt = MANAGER_ENHANCE_PROMPT.format(task_text=task_text)

        try:
            response = self.call_llm(
                [{"role": "user", "content": prompt}],
                system=system, max_tokens=512,
            )
        except Exception as e:
            logger.error(f"LLM enhance failed: {e}")
            return self._create_task(task_text[:80], task_text, 2, "telegram")

        data = self.parse_json(response)
        if not data:
            return self._create_task(task_text[:80], task_text, 2, "telegram")

        title = data.get("title", task_text[:80])
        description = data.get("description", task_text)
        priority = data.get("priority", 3)

        if data.get("ready", True):
            page_id = self._create_task(title, description, priority, "telegram")
            _send_telegram(
                self.config,
                f"Got it! Created task: **{title}**\nAdded to your Notion planning board."
            )
            return page_id
        else:
            # Create in Notion as Inbox (waiting for clarification)
            question = data.get("question", "Could you provide more details?")
            page_id = notion_actions.create_task(
                self._token, self._db_id,
                title=title, description=description,
                priority=priority, source="telegram",
                status="Inbox", note=f"Awaiting clarification: {question}",
            )
            if page_id:
                self.db.send_message("manager", "ceo", page_id, question)
                _send_telegram(
                    self.config,
                    f"Quick question before I add this to the board:\n\n{question}"
                )
                print(f"  Manager: Asked CEO for clarification on '{title}': {question[:60]}")
                self.db.log("manager", "clarification_sent", question[:80], page_id)
                self.memory.write_daily_log(
                    self.db,
                    f"Asked CEO for clarification on '{title}': {question}"
                )
            return page_id

    def _check_pending_clarifications(self) -> bool:
        """Check if CEO replied to any pending Inbox tasks. Returns True if any resolved."""
        inbox_tasks = notion_actions.list_tasks(self._token, self._db_id, status="Inbox")
        resolved = False
        for task in inbox_tasks:
            page_id = task["page_id"]
            ceo_msgs = self.db.get_unread_messages_for_task(page_id, from_role="ceo")
            if not ceo_msgs:
                continue
            reply = ceo_msgs[-1]["content"]
            self.db.mark_messages_read("manager", page_id)

            enhanced_desc = task["description"] + f"\n\nCEO clarification: {reply}"
            notion_actions.update_task(
                self._token, page_id,
                status="Ready",
                note=f"CEO clarified: {reply[:500]}",
            )
            # Also update description
            try:
                import httpx
                httpx.patch(
                    f"{notion_actions.NOTION_API}/pages/{page_id}",
                    headers=notion_actions._headers(self._token),
                    json={"properties": {"Description": {"rich_text": [{"text": {"content": enhanced_desc[:2000]}}]}}},
                    timeout=10,
                )
            except Exception:
                pass

            _send_telegram(
                self.config,
                f"Thanks! **{task['title']}** is now on the board and ready to work on."
            )
            print(f"  Manager: Clarification received, task '{task['title']}' → Ready")
            self.memory.write_daily_log(
                self.db,
                f"CEO clarified '{task['title']}': {reply[:100]}. Moved to Ready."
            )
            resolved = True
        return resolved

    def _handle_ceo_messages(self) -> bool:
        """Route CEO messages: to oldest waiting task (Inbox/Blocked) first, else as new tasks."""
        msgs = self.db.get_unread_messages("manager")
        if not msgs:
            return False

        handled = False
        for msg in msgs:
            if msg["from_role"] != "ceo":
                continue

            # Already bound to a specific task — nothing to re-route
            if msg.get("task_id"):
                handled = True
                continue

            # Find oldest task waiting for CEO input (Inbox or Blocked)
            waiting = (
                notion_actions.list_tasks(self._token, self._db_id, status="Inbox") +
                notion_actions.list_tasks(self._token, self._db_id, status="Blocked")
            )
            waiting.sort(key=lambda t: t.get("last_edited_time", ""))

            if waiting:
                target = waiting[0]
                page_id = target["page_id"]
                # Associate this reply with the waiting task so the resolution methods find it
                self.db.send_message("ceo", "manager", page_id, msg["content"])
                print(f"  Manager: CEO reply → task '{target['title']}' ({target['status']}): {msg['content'][:60]}")
            else:
                print(f"  Manager: New CEO request: {msg['content'][:80]}")
                self.handle_new_ceo_task(msg["content"])
            handled = True

        self.db.mark_messages_read("manager")
        return handled

    def _classify_and_create(self, notification: dict) -> str | None:
        """Classify an email notification and create a task if actionable. Returns page_id."""
        subject = notification.get("subject", "No subject")
        sender = notification.get("from", "Unknown")
        date = notification.get("date", "")

        system = self.get_system_prompt()
        try:
            response = self.call_llm(
                [{"role": "user", "content": f"Email from: {sender}\nSubject: {subject}\nDate: {date}\n\nClassify this."}],
                system=system + "\n\n" + MANAGER_CLASSIFY_PROMPT,
                max_tokens=512,
            )
        except Exception as e:
            logger.error(f"LLM classify failed: {e}")
            return None

        data = self.parse_json(response)
        if not data or not data.get("actionable", False):
            return None

        return self._create_task(
            data.get("title", subject[:80]),
            data.get("description", f"From: {sender}\nSubject: {subject}"),
            min(max(data.get("priority", 3), 1), 4),
            f"email:{sender}",
        )

    def _create_task(self, title: str, description: str, priority: int,
                     source: str) -> str | None:
        """Create task in Notion. Returns page_id."""
        page_id = notion_actions.create_task(
            self._token, self._db_id,
            title=title, description=description,
            priority=priority, source=source,
            status="Ready",
        )
        if page_id:
            print(f"  Manager: Created task '{title}' (P{priority})")
            self.db.log("manager", "task_created", title, page_id)
            self.memory.write_daily_log(
                self.db, f"Created task '{title}' (P{priority}) from {source}."
            )
        return page_id

    def _check_stale_tasks(self) -> int:
        """Re-queue stale In Progress tasks (worker likely died). Returns count."""
        stale = notion_actions.get_stale_tasks(
            self._token, self._db_id,
            minutes=self.config.stale_task_minutes,
        )
        for task in stale:
            notion_actions.update_task(
                self._token, task["page_id"],
                status="Ready", note="Re-queued: worker appears stale.",
            )
            print(f"  Manager: Re-queued stale task '{task['title']}'")
            self.db.log("manager", "task_requeued", task["title"], task["page_id"])
        return len(stale)

    def _check_blocked_tasks(self) -> bool:
        """Check for Blocked tasks. If CEO replied, re-queue. Otherwise, ask CEO via Telegram."""
        blocked = notion_actions.list_tasks(self._token, self._db_id, status="Blocked")
        if not blocked:
            return False

        handled = False
        for task in blocked:
            page_id = task["page_id"]

            # Check if CEO already replied to this blocker
            ceo_reply = self.db.get_unread_messages_for_task(page_id, from_role="ceo")
            if ceo_reply:
                reply = ceo_reply[-1]["content"]
                self.db.mark_messages_read("manager", page_id)
                enhanced = task["description"] + f"\n\nCEO input: {reply}"
                # Update description + status in Notion
                notion_actions.update_task(
                    self._token, page_id,
                    status="Ready", note=f"CEO input: {reply[:200]}",
                )
                try:
                    import httpx
                    httpx.patch(
                        f"{notion_actions.NOTION_API}/pages/{page_id}",
                        headers=notion_actions._headers(self._token),
                        json={"properties": {"Description": {"rich_text": [{"text": {"content": enhanced[:2000]}}]}}},
                        timeout=10,
                    )
                except Exception:
                    pass
                _send_telegram(self.config, f"Got it! Re-queuing **{task['title']}** with your input.")
                self.memory.write_daily_log(
                    self.db, f"CEO input for '{task['title']}': {reply[:100]}. Re-queued."
                )
                handled = True
                continue

            # Check if we already asked CEO about this (avoid repeat Telegram messages)
            existing_msgs = self.db.get_task_messages(page_id)
            already_asked = any(
                m["from_role"] == "manager" and m["to_role"] == "ceo" for m in existing_msgs
            )
            if already_asked:
                continue

            # LLM call: formulate a clear question for CEO based on the blocker
            system = self.get_system_prompt()
            task_info = (
                f"Task: {task['title']}\n"
                f"Description: {task['description']}\n"
                f"Notes (blocker reason): {task.get('notes', '')[:500]}"
            )
            prompt = (
                f"This task is BLOCKED. The worker couldn't proceed.\n\n{task_info}\n\n"
                f"Formulate ONE clear, specific question to ask the CEO so this task can be unblocked. "
                f"Respond with JSON: {{\"question\": \"...\"}}"
            )

            try:
                response = self.call_llm(
                    [{"role": "user", "content": prompt}],
                    system=system, max_tokens=256,
                )
                data = self.parse_json(response)
                question = (
                    data.get("question", f"Task '{task['title']}' is blocked. What should I do?")
                    if data
                    else f"Task '{task['title']}' is blocked. Can you help?"
                )
            except Exception:
                question = f"Task '{task['title']}' is blocked: {task.get('notes', 'unknown reason')[:200]}"

            self.db.send_message("manager", "ceo", page_id, question)
            _send_telegram(self.config, f"Task **{task['title']}** is blocked:\n\n{question}")
            self.db.log("manager", "blocked_question", question[:80], page_id)
            self.memory.write_daily_log(
                self.db, f"Asked CEO about blocked task '{task['title']}': {question[:100]}"
            )
            handled = True

        return handled
