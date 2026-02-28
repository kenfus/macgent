"""File-based memory manager: soul + skills + core memory + daily logs + semantic recall."""

from __future__ import annotations

import datetime
import json
import logging
import math
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
        self.task_history_dir = self.memory_root / "task_history"
        self.semantic_path = self.memory_root / "semantic_memories.jsonl"
        self.core_memory_path = self.agent_dir / "memory" / "CORE_MEMORY.md"
        self.recent_days = max(1, int(getattr(config, "memory_recent_days", 2)))
        self.top_k = max(1, int(getattr(config, "memory_top_k", 5)))

        self._embedder = None
        self._ensure_workspace()

    def _ensure_workspace(self):
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "skills").mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.task_history_dir.mkdir(parents=True, exist_ok=True)
        if not self.semantic_path.exists():
            self.semantic_path.write_text("")

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
        """Load role identity from preferred lowercase file with uppercase fallback."""
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
        """Append cleaned text to today's daily memory file.

        File path is always:
        {{WORKSPACE_DIR}}//memory/<YYYY-MM-DD>_MEMORY.md
        """
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

    def _safe_task_id(self, task_id: str | int) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id))

    def _task_history_path(self, task_id: str | int) -> Path:
        return self.task_history_dir / f"{self._safe_task_id(task_id)}.jsonl"

    def get_short_term(self, db, task_id, role: str | None = None, limit: int = 10) -> list[dict]:
        if not task_id:
            return []
        path = self._task_history_path(task_id)
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if role and row.get("role") != role:
                continue
            out.append(row)
        return out[-max(1, limit):]

    def record_turn(self, db, task_id, role: str, turn_type: str, content: str):
        if not task_id:
            return
        path = self._task_history_path(task_id)
        entry = {
            "task_id": str(task_id),
            "role": role,
            "type": turn_type,
            "content": content,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_semantic_entries(self) -> list[dict]:
        if not self.semantic_path.exists():
            return []
        rows = []
        for line in self.semantic_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _write_semantic_entries(self, rows: list[dict]):
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        if text:
            text += "\n"
        self.semantic_path.write_text(text)

    def _get_embedder(self):
        if self._embedder is not None:
            return self._embedder
        try:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            return self._embedder
        except Exception:
            logger.debug("fastembed unavailable; using lexical recall fallback")
            return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return -1.0
        return dot / (na * nb)

    @staticmethod
    def _lexical_score(query: str, text: str) -> float:
        q = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        t = {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}
        if not q or not t:
            return 0.0
        inter = len(q & t)
        return inter / len(q)

    def remember(self, db, role: str, content: str, category: str = "lesson", task_id=None, confidence: float = 1.0):
        entry = {
            "id": datetime.datetime.now(datetime.UTC).isoformat(),
            "role": role,
            "content": content,
            "category": category,
            "task_id": str(task_id) if task_id is not None else "",
            "confidence": float(confidence),
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        rows = self._load_semantic_entries()
        rows.append(entry)
        self._write_semantic_entries(rows)
        return entry["id"]

    def recall(self, db, role: str, query: str, top_k: int | None = None) -> list[dict]:
        rows = self._load_semantic_entries()
        if not rows:
            return []
        filtered = [r for r in rows if not role or r.get("role") == role]
        if not filtered:
            return []

        k = max(1, int(top_k or self.top_k))
        embedder = self._get_embedder()

        if not embedder:
            scored = []
            for row in filtered:
                score = self._lexical_score(query, row.get("content", ""))
                if score > 0:
                    scored.append((score, row))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [r for _, r in scored[:k]]

        # Ensure embeddings exist for all rows we may score
        query_vec = list(embedder.embed([query]))[0]
        changed = False
        vec_map: dict[str, list[float]] = {}
        for row in rows:
            if "embedding" not in row:
                row["embedding"] = list(embedder.embed([row.get("content", "")]))[0].tolist()
                changed = True
            vec_map[row["id"]] = row.get("embedding", [])
        if changed:
            self._write_semantic_entries(rows)

        scored = []
        qv = query_vec.tolist()
        for row in filtered:
            rv = vec_map.get(row["id"], [])
            if not rv:
                continue
            score = self._cosine(qv, rv)
            row_scored = dict(row)
            row_scored["score"] = float(score)
            scored.append((score, row_scored))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]

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

        if task_id:
            turns = self.get_short_term(db, task_id, limit=10)
            if turns:
                lines = []
                for t in turns:
                    lines.append(f"[{t.get('role','?')}] ({t.get('type','?')}): {t.get('content','')}")
                sections.append(("Recent Task History", "\n".join(lines)))

        if task_description:
            memories = self.recall(db, role, task_description, top_k=self.top_k)
            if memories:
                lines = []
                for m in memories:
                    lines.append(f"- [{m.get('category','memory')}] {m.get('content','')}")
                sections.append((f"Relevant Memory Chunks (top {self.top_k})", "\n".join(lines)))

        return self.combine_markdown_sections(sections)

    def write_daily_log(self, db, content: str, role: str = "agent"):
        self.append_to_daily_memory(content)
        self.remember(db, role, content, category="daily_log")

    def get_today_memory(self) -> str:
        path = self._daily_memory_path(datetime.date.today())
        return path.read_text() if path.exists() else ""

    def embed_past_logs(self, db, days: int = 3):
        # File-based memory does embedding lazily at recall time.
        return None
