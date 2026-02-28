"""File-based memory manager: soul + skills + core memory + daily logs."""

from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path

logger = logging.getLogger("macgent.memory")


class MemoryManager:
    # Core skills shipped with the package
    _CORE_SKILLS_DIR = Path(__file__).parent / "skills"

    def __init__(self, config):
        self.config = config
        self.workspace_dir = Path(config.workspace_dir)
        self.agent_dir = self.workspace_dir / "agent"

        self.memory_root = self.workspace_dir / "memory"
        self.daily_dir = self.memory_root
        self.core_memory_path = self.agent_dir / "memory" / "CORE_MEMORY.md"
        self.recent_days = max(1, int(getattr(config, "memory_recent_days", 2)))

        self._ensure_workspace()

    def _ensure_workspace(self):
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "skills").mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def _render_vars(self, text: str) -> str:
        return (text or "").replace("{{WORKSPACE_DIR}}", str(self.workspace_dir))

    def load_soul(self, role: str) -> str:
        candidates = [
            self.workspace_dir / role / "SOUL.md",
            self.workspace_dir / role / "soul.md",
        ]
        for soul_path in candidates:
            if soul_path.exists():
                return self._render_vars(soul_path.read_text())
        return f"You are the {role} agent."

    def load_identity(self, role: str) -> str:
        upper = self.workspace_dir / role / "IDENTITY.md"
        lower = self.workspace_dir / role / "identity.md"
        if upper.exists():
            return self._render_vars(upper.read_text())
        if lower.exists():
            return self._render_vars(lower.read_text())
        return ""

    def load_core_memory(self) -> str:
        candidates = [
            self.agent_dir / "memory" / "CORE_MEMORY.md",
            self.workspace_dir / "core_memory.md",
        ]
        for p in candidates:
            if p.exists():
                return self._render_vars(p.read_text())
        # Backward-compat fallback for older layout.
        for role in ("manager", "worker"):
            legacy = self.workspace_dir / role / "core_memory.md"
            if legacy.exists():
                return self._render_vars(legacy.read_text())
        return ""

    def load_curated_memory(self, role: str) -> str:
        candidates = [
            self.workspace_dir / role / "memory" / "LONGTERM_MEMORY.md",
            self.workspace_dir / role / "MEMORY.md",
        ]
        for path in candidates:
            if path.exists():
                return self._render_vars(path.read_text())
        return ""

    def get_heartbeat_instructions(self) -> str:
        candidates = [self.workspace_dir / "agent" / "HEARTBEAT.md"]
        for path in candidates:
            if path.exists():
                return self._render_vars(path.read_text())
        return ""

    def _daily_memory_path(self, day: datetime.date) -> Path:
        return self.daily_dir / f"{day.isoformat()}_MEMORY.md"

    def append_to_daily_memory(self, text: str) -> str:
        """Append text to today's daily memory file."""
        today = datetime.date.today()
        path = self._daily_memory_path(today)
        path.parent.mkdir(parents=True, exist_ok=True)

        cleaned = (text or "").strip()
        if not cleaned:
            return str(path)

        with open(path, "a", encoding="utf-8") as f:
            f.write(cleaned + "\n")
        return str(path)

    def get_recent_memory(self, days: int | None = None) -> str:
        parts = []
        for i in range(days or self.recent_days):
            day = datetime.date.today() - datetime.timedelta(days=i)
            path = self._daily_memory_path(day)
            if not path.exists():
                continue
            content = path.read_text().strip()
            if content:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    def load_skills(self) -> str:
        parts = []
        if self._CORE_SKILLS_DIR.exists():
            for path in sorted(self._CORE_SKILLS_DIR.glob("*.md")):
                content = path.read_text().strip()
                if content:
                    parts.append(content)
        learned_dir = self.workspace_dir / "skills"
        if learned_dir.exists():
            for path in sorted(learned_dir.glob("*.md")):
                content = path.read_text().strip()
                if content:
                    parts.append(content)
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def combine_markdown_sections(parts: list[tuple[str, str]]) -> str:
        """Combine markdown sections into one context string."""
        chunks = []
        for title, body in parts:
            b = (body or "").strip()
            if not b:
                continue
            chunks.append(f"# {title}\n\n{b}")
        return "\n\n---\n\n".join(chunks)

    def build_context(self, db, role: str, task_id=None, task_description: str = "") -> str:
        sections: list[tuple[str, str]] = []

        now = datetime.datetime.now()
        sections.append(("Current Date & Time", now.strftime("%Y-%m-%d %H:%M (%A)")))

        soul = self.load_soul(role)
        if soul:
            sections.append(("Soul", soul))

        identity = self.load_identity(role)
        if identity:
            sections.append(("Identity", identity))

        skills = self.load_skills()
        if skills:
            sections.append(("Skills", skills))

        core_memory = self.load_core_memory()
        if core_memory:
            sections.append(("Core Memory", core_memory))

        curated = self.load_curated_memory(role)
        if curated:
            sections.append(("Role Memory", curated))

        recent = self.get_recent_memory(days=self.recent_days)
        if recent:
            sections.append((f"Recent Memory (last {self.recent_days} days)", recent))

        return self.combine_markdown_sections(sections)

    def get_today_memory(self) -> str:
        path = self._daily_memory_path(datetime.date.today())
        return path.read_text() if path.exists() else ""
