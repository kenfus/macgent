"""File-based memory manager: soul + skills + daily logs + long-term memory."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

logger = logging.getLogger("macgent.memory")

MEMORY_SEPARATOR = "\n---\n"


# ---------------------------------------------------------------------------
# Workday helpers
# ---------------------------------------------------------------------------

def current_workday(start_hour: int = 4) -> datetime.date:
    """Return the current 'workday' date.

    A workday runs from ``start_hour`` (default 04:00) to ``start_hour`` the
    next calendar day.  Before 04:00 AM we are still on the *previous*
    workday — matching real human schedules where late-night activity belongs
    to the day that just ended, not the new calendar day.
    """
    now = datetime.datetime.now()
    if now.hour < start_hour:
        return (now - datetime.timedelta(days=1)).date()
    return now.date()


def prev_workday(start_hour: int = 4) -> datetime.date:
    """Return the workday that ended at the most recent ``start_hour``."""
    return current_workday(start_hour) - datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    # Core skills shipped with the package
    _CORE_SKILLS_DIR = Path(__file__).parent / "skills"

    def __init__(self, config):
        self.config = config
        self.workspace_dir = Path(config.workspace_dir)
        self.agent_dir = self.workspace_dir / "agent"
        # All memory files live together under agent/memory/
        self.memory_dir = self.agent_dir / "memory"
        self.workday_start_hour: int = int(getattr(config, "workday_start_hour", 4))

        self._ensure_workspace()
        self._migrate_legacy_daily_files()

    # ------------------------------------------------------------------
    # Bootstrap / directories
    # ------------------------------------------------------------------

    def _ensure_workspace(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "skills").mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _migrate_legacy_daily_files(self) -> None:
        """Move any daily MEMORY files from the old workspace/memory/ to agent/memory/."""
        old_dir = self.workspace_dir / "memory"
        if not old_dir.is_dir():
            return
        moved = 0
        for src in list(old_dir.glob("*_MEMORY.md")) + list(old_dir.glob(".distilled_*")):
            dst = self.memory_dir / src.name
            if not dst.exists():
                src.rename(dst)
                moved += 1
        if moved:
            logger.info("Migrated %d memory file(s) from workspace/memory/ to agent/memory/", moved)

    # ------------------------------------------------------------------
    # Template variable substitution
    # ------------------------------------------------------------------

    def _render_vars(self, text: str) -> str:
        return (text or "").replace("{{WORKSPACE_DIR}}", str(self.workspace_dir))

    # ------------------------------------------------------------------
    # Soul / identity / skill loading
    # ------------------------------------------------------------------

    def load_soul(self, role: str) -> str:
        for name in ("SOUL.md", "soul.md"):
            p = self.workspace_dir / role / name
            if p.exists():
                return self._render_vars(p.read_text())
        return f"You are the {role} agent."

    def load_identity(self, role: str) -> str:
        for name in ("IDENTITY.md", "identity.md"):
            p = self.workspace_dir / role / name
            if p.exists():
                return self._render_vars(p.read_text())
        return ""

    def load_longterm_memory(self, role: str) -> str:
        p = self.agent_dir / "memory" / "LONGTERM_MEMORY.md"
        if p.exists():
            return self._render_vars(p.read_text())
        # Legacy fallback
        for alt in (self.workspace_dir / role / "MEMORY.md",):
            if alt.exists():
                return self._render_vars(alt.read_text())
        return ""

    # Keep alias so any existing call-sites don't break.
    def load_curated_memory(self, role: str) -> str:
        return self.load_longterm_memory(role)

    def load_skills(self) -> str:
        parts: list[str] = []
        if self._CORE_SKILLS_DIR.exists():
            for p in sorted(self._CORE_SKILLS_DIR.glob("*.md")):
                content = p.read_text().strip()
                if content:
                    parts.append(content)
        learned_dir = self.workspace_dir / "skills"
        if learned_dir.exists():
            for p in sorted(learned_dir.glob("*.md")):
                content = p.read_text().strip()
                if content:
                    parts.append(content)
        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------
    # Daily memory files
    # ------------------------------------------------------------------

    def _daily_memory_path(self, day: datetime.date) -> Path:
        return self.memory_dir / f"{day.isoformat()}_MEMORY.md"

    def ensure_today_memory_file(self) -> Path:
        """Create today's daily memory file if it does not yet exist."""
        today = current_workday(self.workday_start_hour)
        path = self._daily_memory_path(today)
        if not path.exists():
            path.touch()
            logger.info("Created today's memory file: %s", path.name)
        return path

    def append_to_daily_memory(self, text: str) -> str:
        """Append *text* to today's workday memory file."""
        path = self.ensure_today_memory_file()
        cleaned = (text or "").strip()
        if not cleaned:
            return str(path)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        with open(path, "a", encoding="utf-8") as f:
            if existing.strip():
                f.write(MEMORY_SEPARATOR + cleaned)
            else:
                f.write(cleaned)
        return str(path)

    def get_today_memory(self) -> str:
        path = self._daily_memory_path(current_workday(self.workday_start_hour))
        return path.read_text() if path.exists() else ""

    def _cleanup_old_daily_files(self, keep_workdays: int = 2) -> None:
        """Delete daily memory files older than *keep_workdays* workdays."""
        cutoff = current_workday(self.workday_start_hour) - datetime.timedelta(days=keep_workdays)
        for p in self.memory_dir.glob("*_MEMORY.md"):
            try:
                day_str = p.stem.replace("_MEMORY", "")
                day = datetime.date.fromisoformat(day_str)
                if day < cutoff:
                    p.unlink()
                    logger.info("Deleted old daily memory file: %s", p.name)
            except ValueError:
                pass  # non-date filename, leave it alone

    # ------------------------------------------------------------------
    # Context builder (system prompt)
    # ------------------------------------------------------------------

    @staticmethod
    def combine_markdown_sections(parts: list[tuple[str, str]]) -> str:
        chunks = []
        for title, body in parts:
            b = (body or "").strip()
            if not b:
                continue
            chunks.append(f"# {title}\n\n{b}")
        return "\n\n---\n\n".join(chunks)

    def build_context(self, db, role: str, task_id=None, task_description: str = "") -> str:
        """Build the full system-prompt context for one agent tick."""
        sections: list[tuple[str, str]] = []

        today = current_workday(self.workday_start_hour)
        yesterday = today - datetime.timedelta(days=1)
        now = datetime.datetime.now()

        sections.append(("Current Date & Time", now.strftime("%Y-%m-%d %H:%M (%A)")))

        soul = self.load_soul(role)
        if soul:
            sections.append(("Soul", soul))

        identity = self.load_identity(role)
        if identity:
            sections.append(("Identity", identity))

        longterm = self.load_longterm_memory(role)
        if longterm:
            sections.append(("Long-term Memory", longterm))

        yesterday_path = self._daily_memory_path(yesterday)
        if yesterday_path.exists():
            content = yesterday_path.read_text().strip()
            if content:
                sections.append((f"Yesterday's Memory ({yesterday.isoformat()})", content))

        today_path = self._daily_memory_path(today)
        if today_path.exists():
            content = today_path.read_text().strip()
            if content:
                sections.append((f"Today's Memory ({today.isoformat()})", content))

        skills = self.load_skills()
        if skills:
            sections.append(("Skills", skills))

        return self.combine_markdown_sections(sections)
