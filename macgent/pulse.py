"""System pulse — lightweight Python-only maintenance loop.

Runs every ~60 seconds alongside the agent heartbeat (which runs every 30 min).
The pulse handles time-based maintenance tasks without invoking the LLM.
At the workday boundary it does Python-only cleanup (file creation / old file purge).
All scheduled wakeup tasks (including memory distillation) are configured in
``workspace/agent/PULSE_SCHEDULE.json`` and managed by the agent itself.

## Built-in tasks

**Workday transition at 04:01** (workday boundary + 1 min):
  Creates today's daily memory file and deletes daily files older than 2 workdays.
  Fires once per workday (tracked in ``_fired_today``, reset on workday change).

## Agent-configurable schedule

The agent schedules wakeup tasks by writing to ``workspace/agent/PULSE_SCHEDULE.json``:

    [
      {
        "id": "memory_distillation",
        "time": "04:01",
        "description": "Read agent/memory/{prev_workday}_MEMORY.md and update LONGTERM_MEMORY.md"
      }
    ]

Each entry fires once per workday (``_fired_today`` set, reset on workday change).
Supported template variables in description: ``{prev_workday}``, ``{today}``.
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
        """At 04:01 on a new workday: Python-only file maintenance."""
        maintenance_key = f"maintenance_{today.isoformat()}"
        if maintenance_key in self._fired_today:
            return  # Already handled this workday

        now = datetime.datetime.now()
        if now.hour < self._workday_start_hour:
            return  # Not past the workday boundary yet
        if now.hour == self._workday_start_hour and now.minute < 1:
            return  # Wait until HH:01 (one minute after boundary)

        self._fired_today.add(maintenance_key)

        # Python-only maintenance: create today's file, purge old ones
        self.memory.ensure_today_memory_file()
        self.memory._cleanup_old_daily_files(keep_workdays=2)
        logger.info("Pulse: workday transition maintenance complete (new workday: %s)", today)

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
        today = current_workday(self._workday_start_hour)
        previous = prev_workday(self._workday_start_hour)

        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", task.get("time", "")))
            fire_time = str(task.get("time", ""))
            description = str(task.get("description", "Scheduled task"))
            # Template substitution
            description = description.replace("{prev_workday}", previous.isoformat())
            description = description.replace("{today}", today.isoformat())

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
