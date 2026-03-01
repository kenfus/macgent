"""System pulse — lightweight Python-only maintenance loop.

Runs every ~60 seconds alongside the agent heartbeat (which runs every 30 min).
The pulse handles time-based maintenance tasks *without* invoking the LLM except
indirectly: at the workday boundary it injects a wakeup task into the agent queue
so the agent can distill its own memory using its normal read_file / write_file actions.

## Built-in tasks

**Memory distillation at 04:01** (workday boundary + 1 min):
  The pulse creates today's daily memory file, deletes daily files older than 2
  workdays, and sends a "system" message to the agent asking it to read the
  previous workday's log and update LONGTERM_MEMORY.md as it sees fit.
  Fires once per workday (tracked in ``_fired_today``, reset on workday change).

## Agent-configurable schedule

The agent can schedule itself to be woken at specific times by writing to
``workspace/agent/PULSE_SCHEDULE.json``:

    [
      {
        "id": "morning-briefing",
        "time": "09:00",
        "description": "Check calendar and send a morning summary to the CEO"
      }
    ]

Each entry fires once per workday (``_fired_today`` set, reset on workday change).
On daemon restart within the same workday the set is empty, so tasks may re-fire —
this is intentional; idempotent agent tasks handle it gracefully.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

from macgent import message_bus
from macgent.memory import current_workday, prev_workday

logger = logging.getLogger("macgent.pulse")

_SCHEDULE_RELATIVE_PATH = "agent/PULSE_SCHEDULE.json"


class SystemPulse:
    """Maintenance pulse — call ``tick()`` every ~60 seconds."""

    def __init__(self, config, memory):
        self.config = config
        self.memory = memory
        self._workday_start_hour: int = int(getattr(config, "workday_start_hour", 4))
        # Track which task IDs already fired this workday (resets on workday change)
        self._fired_today: set[str] = set()
        self._fired_workday: datetime.date | None = None

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Run one pulse cycle. Should be called every ~60 seconds."""
        today = current_workday(self._workday_start_hour)

        # Reset fired-set when the workday rolls over
        if self._fired_workday != today:
            self._fired_today.clear()
            self._fired_workday = today

        self._check_workday_maintenance(today)
        self._check_schedule()

    # ------------------------------------------------------------------
    # Workday maintenance (04:01 boundary)
    # ------------------------------------------------------------------

    def _check_workday_maintenance(self, today: datetime.date) -> None:
        """At 04:01 on a new workday: Python cleanup + inject distillation task."""
        distill_key = f"distill_{today.isoformat()}"
        if distill_key in self._fired_today:
            return  # Already handled this workday

        now = datetime.datetime.now()
        if now.hour < self._workday_start_hour:
            return  # Not past the workday boundary yet
        if now.hour == self._workday_start_hour and now.minute < 1:
            return  # Wait until HH:01 (one minute after boundary)

        self._fired_today.add(distill_key)

        # Python-only maintenance: create today's file, purge old ones
        self.memory.ensure_today_memory_file()
        self.memory._cleanup_old_daily_files(keep_workdays=2)
        logger.info("Pulse: workday transition maintenance complete (new workday: %s)", today)

        # Inject a wakeup task — the agent reads + updates its own memory
        previous = prev_workday(self._workday_start_hour)
        daily_path = self.memory._daily_memory_path(previous)
        if not daily_path.exists() or not daily_path.read_text().strip():
            logger.info("Pulse: %s is empty — skipping distillation wakeup", daily_path.name)
            return

        prev_rel = f"agent/memory/{previous.isoformat()}_MEMORY.md"
        longterm_rel = "agent/memory/LONGTERM_MEMORY.md"

        task = (
            f"[System: workday memory distillation]\n\n"
            f"Read `{prev_rel}` (previous workday log) and `{longterm_rel}` "
            "(current long-term memory).\n\n"
            "If anything in the daily log is worth keeping permanently — user preferences, "
            "ongoing projects, key facts, relationships, lessons learned — update "
            f"`{longterm_rel}` using write_file, then respond with "
            '`{"type": "pulse_ok"}`.\n\n'
            "If nothing is important, respond directly with "
            '`{"type": "pulse_ok"}`.\n\n'
            "Do NOT send a Telegram message for this routine maintenance task."
        )

        message_bus.enqueue_message("system", "agent", None, task)
        message_bus.request_wake()
        logger.info("Pulse: distillation task injected for workday %s", previous)

    # ------------------------------------------------------------------
    # Agent-configured schedule
    # ------------------------------------------------------------------

    def _check_schedule(self) -> None:
        """Fire any scheduled wakeup tasks whose time has arrived today."""
        schedule_path = Path(self.config.workspace_dir) / _SCHEDULE_RELATIVE_PATH
        if not schedule_path.exists():
            return

        try:
            tasks = json.loads(schedule_path.read_text())
        except Exception as e:
            logger.warning("Pulse: could not read PULSE_SCHEDULE.json: %s", e)
            return

        if not isinstance(tasks, list):
            return

        now = datetime.datetime.now()
        now_hm = now.strftime("%H:%M")

        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", task.get("time", "")))
            fire_time = str(task.get("time", ""))
            description = str(task.get("description", "Scheduled task"))

            if not fire_time or not task_id:
                continue
            if task_id in self._fired_today:
                continue
            if now_hm >= fire_time:
                self._fired_today.add(task_id)
                logger.info("Pulse: firing scheduled task '%s' at %s", task_id, now_hm)
                message_bus.enqueue_message(
                    from_role="system",
                    to_role="agent",
                    task_id=None,
                    content=f"[Scheduled at {fire_time}] {description}",
                )
                message_bus.request_wake()
