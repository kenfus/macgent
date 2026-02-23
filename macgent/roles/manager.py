"""Manager role — heartbeat monitoring, Notion board, daily memory, task creation."""

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

    def _ensure_notion(self):
        """Ensure Notion schema is set up (runs once per session)."""
        if self._notion_ready:
            return
        if self.config.notion_token and self.config.notion_database_id:
            notion_actions.ensure_schema(
                self.config.notion_token, self.config.notion_database_id
            )
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

    def tick(self):
        """One heartbeat: memory → Notion board → email → create tasks → write log."""
        logger.info("Manager tick starting")
        self.db.log("manager", "tick_start")
        self._ensure_notion()

        woken_early = self.should_wake_early()
        if woken_early:
            logger.info("Manager woken by external notification")
            print("  Manager: Woken by external notification!")
            self.clear_wake_request()

        # 1. Load today's memory + recall relevant past context
        today_memory = self.memory.get_today_memory()
        if today_memory:
            print(f"  Manager: Today's memory loaded ({len(today_memory)} chars)")
        recalled = self.memory.recall(self.db, "manager", "daily summary tasks email", top_k=3)
        if recalled:
            print(f"  Manager: Recalled {len(recalled)} relevant memories")

        # 2. Check pending clarifications (CEO replied to manager questions)
        self._check_pending_clarifications()

        # 3. Sync Notion board
        self._sync_notion_board()

        # 4. Check notification sources (email etc.)
        all_notifications = []
        for monitor in self.monitors:
            try:
                items = monitor.check(self.db)
                all_notifications.extend(items)
            except Exception as e:
                logger.error(f"Monitor {monitor.source_name} failed: {e}")
                self.db.log("manager", "monitor_error", f"{monitor.source_name}: {e}")

        # 5. Classify and create tasks from notifications
        created = 0
        for notif in all_notifications:
            try:
                task_id = self._classify_and_create(notif)
                if task_id:
                    created += 1
            except Exception as e:
                logger.error(f"Failed to classify notification: {e}")

        if created:
            print(f"  Manager: Created {created} new tasks from notifications")

        # 6. Handle new direct CEO messages (Telegram)
        self._handle_ceo_messages()

        # 7. Monitor active task progress
        self._report_active_task_progress()

        # 8. Check stale tasks
        self._check_stale_tasks()

        # 9. Board health check
        board_summary = self._check_board_health()

        # 10. Write daily memory log
        log_parts = [f"Heartbeat: {created} new tasks from email."]
        if recalled:
            log_parts.append(f"Recalled {len(recalled)} past memories.")
        if board_summary:
            log_parts.append(board_summary)
        self.memory.write_daily_log(self.db, " ".join(log_parts))

        self.db.log("manager", "tick_done")
        logger.info("Manager tick done")

    def handle_new_ceo_task(self, task_text: str) -> int:
        """Process a new task from CEO (Telegram). Returns task_id."""
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
            return self._create_task_full(task_text[:80], task_text, 2, "telegram")

        data = self.parse_json(response)
        if not data:
            return self._create_task_full(task_text[:80], task_text, 2, "telegram")

        title = data.get("title", task_text[:80])
        description = data.get("description", task_text)
        priority = data.get("priority", 3)

        if data.get("ready", True):
            task_id = self._create_task_full(title, description, priority, "telegram")
            _send_telegram(
                self.config,
                f"Got it! Created task: **{title}**\nAdded to your Notion planning board."
            )
            return task_id
        else:
            # Ask CEO for clarification before creating in Notion
            task_id = self.db.create_task(
                title=title, description=description,
                source="telegram:clarifying", priority=priority,
            )
            self.db.update_task(task_id, status="clarifying")
            question = data.get("question", "Could you provide more details?")
            self.db.send_message("manager", "ceo", task_id, question)
            _send_telegram(
                self.config,
                f"Quick question before I add this to the board:\n\n{question}"
            )
            print(f"  Manager: Asked CEO for clarification on task #{task_id}: {question[:60]}")
            self.db.log("manager", "clarification_sent", question[:80], task_id)
            self.memory.write_daily_log(
                self.db,
                f"Asked CEO for clarification on '{title}': {question}"
            )
            return task_id

    def _check_pending_clarifications(self):
        """Check if CEO replied to any pending clarification requests."""
        clarifying = self.db.list_tasks(status="clarifying")
        for task in clarifying:
            ceo_msgs = self.db.get_unread_messages_for_task(task["id"], from_role="ceo")
            if not ceo_msgs:
                continue
            reply = ceo_msgs[-1]["content"]
            self.db.mark_messages_read("manager", task["id"])

            enhanced_desc = task["description"] + f"\n\nCEO clarification: {reply}"
            self.db.update_task(task["id"], description=enhanced_desc, status="pending")

            page_id = notion_actions.create_task(
                self.config.notion_token,
                self.config.notion_database_id,
                title=task["title"],
                description=enhanced_desc,
                priority=task["priority"],
                source=task["source"],
                status="Ready",
                task_id=task["id"],
            )
            if page_id:
                self.db.set_notion_page_id(task["id"], page_id)

            _send_telegram(
                self.config,
                f"Thanks! **{task['title']}** is now on the board and ready to work on."
            )
            print(f"  Manager: Clarification received, task #{task['id']} → pending + Notion")
            self.memory.write_daily_log(
                self.db,
                f"CEO clarified '{task['title']}': {reply[:100]}. Added to Notion board."
            )

    def _sync_notion_board(self):
        """Check Notion for status updates (e.g. CEO manually changed something)."""
        if not self.config.notion_token or not self.config.notion_database_id:
            return
        try:
            notion_tasks = notion_actions.list_tasks(
                self.config.notion_token, self.config.notion_database_id
            )
            for nt in notion_tasks:
                if nt.get("macgent_id") and nt["status"] in ("Done", "Failed"):
                    local = self.db.get_task(nt["macgent_id"])
                    if local and local["status"] not in ("completed", "failed"):
                        logger.debug(f"Notion task #{nt['macgent_id']} is {nt['status']}")
        except Exception as e:
            logger.debug(f"Notion sync check failed: {e}")

    def _handle_ceo_messages(self):
        """Handle new direct task requests from CEO via Telegram."""
        msgs = self.db.get_unread_messages("manager")
        for msg in msgs:
            if msg["from_role"] == "ceo" and not msg.get("task_id"):
                print(f"  Manager: New CEO request: {msg['content'][:80]}")
                self.handle_new_ceo_task(msg["content"])
        self.db.mark_messages_read("manager")

    def _classify_and_create(self, notification: dict) -> int | None:
        """Classify an email notification and create a task if actionable."""
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

        return self._create_task_full(
            data.get("title", subject[:80]),
            data.get("description", f"From: {sender}\nSubject: {subject}"),
            min(max(data.get("priority", 3), 1), 4),
            f"email:{sender}",
        )

    def _create_task_full(self, title: str, description: str, priority: int,
                          source: str) -> int:
        """Create task in SQLite + Notion. Returns task_id."""
        task_id = self.db.create_task(
            title=title, description=description,
            source=source, priority=priority,
        )
        page_id = notion_actions.create_task(
            self.config.notion_token,
            self.config.notion_database_id,
            title=title, description=description,
            priority=priority, source=source,
            status="Ready", task_id=task_id,
        )
        if page_id:
            self.db.set_notion_page_id(task_id, page_id)

        print(f"  Manager: Created task #{task_id} (P{priority}): {title}")
        self.db.log("manager", "task_created", f"#{task_id}: {title}", task_id)
        self.memory.write_daily_log(
            self.db, f"Created task '{title}' (P{priority}) from {source}."
        )
        return task_id

    def _report_active_task_progress(self):
        in_progress = self.db.list_tasks(status="in_progress")
        for task in in_progress:
            activity = self.db.get_task_recent_activity(task["id"], limit=3)
            if activity:
                last = activity[-1]
                print(f"  Manager: Task #{task['id']} active — {last['action']} {(last['detail'] or '')[:60]}")

    def _check_stale_tasks(self):
        stale = self.db.get_stale_tasks(minutes=self.config.stale_task_minutes)
        for task in stale:
            self.db.send_message(
                "manager", "worker", task["id"],
                f"Task #{task['id']} has been in_progress for over {self.config.stale_task_minutes} minutes. Please update status.",
            )
            print(f"  Manager: Pinged Worker about stale task #{task['id']}")
            self.db.log("manager", "stale_ping", f"Task #{task['id']}", task["id"])

    def _check_board_health(self) -> str:
        pending = self.db.list_tasks(status="pending")
        in_progress = self.db.list_tasks(status="in_progress")
        if pending or in_progress:
            print(f"  Manager: Board — {len(pending)} pending, {len(in_progress)} in progress")
        if len(pending) > 10:
            print(f"  Manager: WARNING — {len(pending)} pending tasks piling up!")
        return f"Board: {len(pending)} pending, {len(in_progress)} in progress."
