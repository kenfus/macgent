"""File-based memory manager: soul + skills + core memory + daily logs + semantic recall."""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("macgent.memory")


MEMORY_SEPARATOR = "\n---\n"


class EmbeddingMemory:
    """FAISS-backed semantic memory store.

    Supports two embedding backends (swap via constructor args):
    - **fastembed** (default): fully local, no API key needed.
      Default model: ``BAAI/bge-small-en-v1.5`` (~130 MB, fast).
    - **OpenAI-compatible API**: set ``embed_api_key`` (and optionally
      ``embed_api_base`` / ``embed_model``) to use any OpenAI-compatible
      embeddings endpoint (OpenAI, Azure, local vLLM, etc.).

    Entries are deduplicated by MD5 hash so re-syncing a file is always safe.
    """

    _DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    _DEFAULT_OPENAI_MODEL = "text-embedding-3-small"

    def __init__(
        self,
        faiss_path: str | Path,
        top_k: int = 5,
        embed_model: str = "",
        embed_api_key: str = "",
        embed_api_base: str = "https://api.openai.com/v1",
    ):
        self.faiss_path = Path(faiss_path)
        self.top_k = top_k
        self.embed_api_key = embed_api_key
        self.embed_api_base = embed_api_base.rstrip("/")
        self.embed_model = embed_model or (
            self._DEFAULT_OPENAI_MODEL if embed_api_key else self._DEFAULT_LOCAL_MODEL
        )
        self._local_model = None
        self._index = None
        self._texts: list[str] = []
        self._hashes: set[str] = set()
        self._load()

    # ------------------------------------------------------------------
    # Embedding backends
    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]):
        import numpy as np
        if self.embed_api_key:
            return self._embed_openai(texts)
        return self._embed_local(texts)

    def _embed_local(self, texts: list[str]):
        import numpy as np
        if self._local_model is None:
            from fastembed import TextEmbedding
            self._local_model = TextEmbedding(model_name=self.embed_model)
        vecs = list(self._local_model.embed(texts))
        return np.array(vecs, dtype=np.float32)

    def _embed_openai(self, texts: list[str]):
        import numpy as np
        import httpx
        resp = httpx.post(
            f"{self.embed_api_base}/embeddings",
            headers={"Authorization": f"Bearer {self.embed_api_key}", "Content-Type": "application/json"},
            json={"model": self.embed_model, "input": texts},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        vecs = [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
        return np.array(vecs, dtype=np.float32)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _meta_path(self) -> Path:
        return self.faiss_path.with_suffix(".meta.json")

    @staticmethod
    def _hash(text: str) -> str:
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()

    def _load(self) -> None:
        try:
            import faiss
            if self.faiss_path.exists() and self._meta_path().exists():
                self._index = faiss.read_index(str(self.faiss_path))
                self._texts = json.loads(self._meta_path().read_text())
                self._hashes = {self._hash(t) for t in self._texts}
                logger.debug("EmbeddingMemory loaded %d entries from %s", len(self._texts), self.faiss_path)
        except Exception as e:
            logger.warning("EmbeddingMemory load failed: %s", e)

    def _save(self) -> None:
        try:
            import faiss
            self.faiss_path.parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(self.faiss_path))
            self._meta_path().write_text(json.dumps(self._texts, ensure_ascii=False))
        except Exception as e:
            logger.warning("EmbeddingMemory save failed: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, text: str) -> bool:
        """Embed and index one entry. Returns True if newly added, False if duplicate."""
        text = text.strip()
        if not text:
            return False
        h = self._hash(text)
        if h in self._hashes:
            return False
        try:
            import faiss
            vec = self._embed([text])
            dim = vec.shape[1]
            if self._index is None:
                self._index = faiss.IndexFlatL2(dim)
            self._index.add(vec)
            self._texts.append(text)
            self._hashes.add(h)
            self._save()
            return True
        except Exception as e:
            logger.warning("EmbeddingMemory.add failed: %s", e)
            return False

    def sync_file(self, path: str | Path) -> int:
        """Read a separator-delimited file and index any chunks not yet seen.

        Chunks are split on ``MEMORY_SEPARATOR`` (``\\n---\\n``).
        Already-indexed chunks are skipped via hash dedup.
        Returns the number of newly added entries.
        """
        path = Path(path)
        if not path.exists():
            return 0
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return 0
        chunks = [c.strip() for c in content.split(MEMORY_SEPARATOR) if c.strip()]
        added = sum(1 for chunk in chunks if self.add(chunk))
        if added:
            logger.debug("EmbeddingMemory.sync_file %s: +%d new entries", path.name, added)
        return added

    def search(self, query: str, top_k: int | None = None) -> list[str]:
        """Return top-k most semantically relevant stored entries for query."""
        if self._index is None or not self._texts:
            return []
        try:
            k = min(top_k or self.top_k, len(self._texts))
            vec = self._embed([query])
            _, indices = self._index.search(vec, k)
            return [self._texts[i] for i in indices[0] if 0 <= i < len(self._texts)]
        except Exception as e:
            logger.warning("EmbeddingMemory.search failed: %s", e)
            return []


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
        self.top_k = int(getattr(config, "memory_top_k", 5))

        self._ensure_workspace()

        # Semantic recall — optional, silently disabled if faiss/fastembed missing
        self._embedding_memory: EmbeddingMemory | None = None
        faiss_path = getattr(config, "faiss_path", "")
        if faiss_path:
            try:
                self._embedding_memory = EmbeddingMemory(
                    faiss_path=faiss_path,
                    top_k=self.top_k,
                    embed_model=getattr(config, "embedding_model", ""),
                    embed_api_key=getattr(config, "embedding_api_key", ""),
                    embed_api_base=getattr(config, "embedding_api_base", "https://api.openai.com/v1"),
                )
            except Exception as e:
                logger.warning("EmbeddingMemory unavailable: %s", e)

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
        """Append text to today's daily memory file.

        Entries are separated by ``MEMORY_SEPARATOR`` (``\\n---\\n``) so the
        file can be chunked by entry for embedding.
        """
        today = datetime.date.today()
        path = self._daily_memory_path(today)
        path.parent.mkdir(parents=True, exist_ok=True)

        cleaned = (text or "").strip()
        if not cleaned:
            return str(path)

        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        with open(path, "a", encoding="utf-8") as f:
            if existing.strip():
                f.write(MEMORY_SEPARATOR + cleaned)
            else:
                f.write(cleaned)

        if self._embedding_memory:
            self._embedding_memory.add(cleaned)

        return str(path)

    def sync_daily_memories(self) -> int:
        """Heartbeat helper: ensure today's file exists, then sync all recent files into FAISS.

        Call this once per heartbeat/pulse. It is idempotent — already-indexed
        chunks are skipped via hash dedup inside EmbeddingMemory.

        Returns the total number of newly indexed entries.
        """
        # Ensure today's file exists (creates an empty one if needed)
        today = datetime.date.today()
        today_path = self._daily_memory_path(today)
        today_path.parent.mkdir(parents=True, exist_ok=True)
        if not today_path.exists():
            today_path.touch()
            logger.debug("Created today's memory file: %s", today_path)

        if not self._embedding_memory:
            return 0

        total = 0
        for i in range(self.recent_days):
            day = today - datetime.timedelta(days=i)
            path = self._daily_memory_path(day)
            if path.exists():
                total += self._embedding_memory.sync_file(path)

        if total:
            logger.info("sync_daily_memories: indexed %d new entries", total)
        return total

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

        if self._embedding_memory and task_description:
            relevant = self._embedding_memory.search(task_description, self.top_k)
            if relevant:
                sections.append(("Relevant Past Experience", "\n\n---\n\n".join(relevant)))

        return self.combine_markdown_sections(sections)

    def get_today_memory(self) -> str:
        path = self._daily_memory_path(datetime.date.today())
        return path.read_text() if path.exists() else ""
