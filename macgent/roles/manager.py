"""Manager role — heartbeat monitoring, task creation, board management."""

import logging
from macgent.roles.base import BaseRole
from macgent.monitors.email_monitor import EmailMonitor
from macgent.prompts.role_prompts import MANAGER_CLASSIFY_PROMPT, MANAGER_BOARD_PROMPT

logger = logging.getLogger("macgent.roles.manager")


class ManagerRole(BaseRole):
    role_name = "manager"

    def __init__(self, config, db, memory):
        super().__init__(config, db, memory)
        # Active monitors - check these sources during each heartbeat
        self.monitors = [EmailMonitor()]
        # TODO: Add more monitors as needed
        # from macgent.monitors.notion_monitor import NotionMonitor
        # from macgent.monitors.slack_monitor import SlackMonitor
        # self.monitors.extend([NotionMonitor(), SlackMonitor()])

    def should_wake_early(self) -> bool:
        """Check if an external system has requested an immediate heartbeat."""
        row = self.db.conn.execute(
            "SELECT metadata FROM monitor_state WHERE source = ?",
            ("_wake_request",)
        ).fetchone()
        return bool(row)

    def clear_wake_request(self):
        """Clear the wake request after handling it."""
        self.db.conn.execute("DELETE FROM monitor_state WHERE source = ?", ("_wake_request",))
        self.db.conn.commit()

    def tick(self):
        """One heartbeat cycle: check notifications, manage board."""
        logger.info("Manager tick starting")
        self.db.log("manager", "tick_start")

        # Check if woken by external notification
        woken_early = self.should_wake_early()
        if woken_early:
            logger.info("Manager woken by external notification (Telegram, Slack, etc.)")
            print("  Manager: Woken by external notification!")
            self.clear_wake_request()

        # 1. Check all notification sources
        all_notifications = []
        for monitor in self.monitors:
            try:
                items = monitor.check(self.db)
                all_notifications.extend(items)
                logger.info(f"Monitor {monitor.source_name}: {len(items)} items")
            except Exception as e:
                logger.error(f"Monitor {monitor.source_name} failed: {e}")
                self.db.log("manager", "monitor_error",
                            f"{monitor.source_name}: {e}")

        # 2. Classify and create tasks for actionable notifications
        created = 0
        for notif in all_notifications:
            try:
                task_id = self._classify_and_create(notif)
                if task_id:
                    created += 1
            except Exception as e:
                logger.error(f"Failed to classify notification: {e}")

        if created:
            print(f"  Manager: created {created} new tasks from notifications")
            self.db.log("manager", "tasks_created", f"Created {created} tasks")

        # 3. Check stale tasks
        self._check_stale_tasks()

        # 4. Review board health
        self._check_board_health()

        self.db.log("manager", "tick_done")
        logger.info("Manager tick done")

    def _classify_and_create(self, notification: dict) -> int | None:
        """Use LLM to classify a notification and optionally create a task."""
        subject = notification.get("subject", "No subject")
        sender = notification.get("from", "Unknown")
        date = notification.get("date", "")

        system = self.get_system_prompt()
        messages = [{
            "role": "user",
            "content": f"Email from: {sender}\nSubject: {subject}\nDate: {date}\n\nClassify this.",
        }]

        try:
            response = self.call_llm(
                messages, system=system + "\n\n" + MANAGER_CLASSIFY_PROMPT,
                max_tokens=512,
            )
        except Exception as e:
            logger.error(f"LLM classify failed: {e}")
            return None

        data = self.parse_json(response)
        if not data:
            logger.warning(f"Could not parse classification: {response[:200]}")
            return None

        if not data.get("actionable", False):
            logger.info(f"Not actionable: {subject} — {data.get('reason', '')}")
            self.db.log("manager", "not_actionable",
                        f"{subject}: {data.get('reason', '')}")
            return None

        title = data.get("title", subject[:80])
        description = data.get("description", f"From: {sender}\nSubject: {subject}")
        priority = data.get("priority", 3)

        task_id = self.db.create_task(
            title=title,
            description=description,
            source=f"email:{sender}",
            priority=min(max(priority, 1), 4),
        )
        print(f"  Manager: Created task #{task_id} (P{priority}): {title}")
        self.db.log("manager", "task_created", f"#{task_id}: {title}", task_id)
        return task_id

    def _check_stale_tasks(self):
        """Ping Worker about tasks stuck in_progress too long."""
        stale = self.db.get_stale_tasks(minutes=self.config.stale_task_minutes)
        for task in stale:
            self.db.send_message(
                "manager", "worker", task["id"],
                f"Task #{task['id']} has been in_progress for over {self.config.stale_task_minutes} minutes. Please update status.",
            )
            print(f"  Manager: Pinged Worker about stale task #{task['id']}")
            self.db.log("manager", "stale_ping", f"Task #{task['id']}", task["id"])

    def _check_board_health(self):
        """Check overall board status and alert if needed."""
        pending = self.db.list_tasks(status="pending")
        in_progress = self.db.list_tasks(status="in_progress")
        review = self.db.list_tasks(status="review")

        if len(pending) > 10:
            print(f"  Manager: WARNING — {len(pending)} pending tasks piling up!")
            self.db.log("manager", "board_warning",
                        f"{len(pending)} pending tasks")

        total_active = len(pending) + len(in_progress) + len(review)
        if total_active > 0:
            print(f"  Manager: Board — {len(pending)} pending, {len(in_progress)} in progress, {len(review)} in review")
