"""Memory system: Soul files + short-term (SQLite) + long-term (FAISS + fastembed) + daily logs."""

import datetime
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("macgent.memory")


class MemoryManager:
    # Path to core (fixed) skills shipped inside the package
    _CORE_SKILLS_DIR = Path(__file__).parent / "skills"

    def __init__(self, config):
        self.config = config
        self.workspace_dir = Path(config.workspace_dir)
        self.faiss_path = config.faiss_path
        self.memories_dir = Path(config.memories_dir)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

        self._embedder = None
        self._index = None
        self._id_map = []  # Maps FAISS position → SQLite memory ID

        self._ensure_workspace()

    def _ensure_workspace(self):
        """Create workspace directory structure if it doesn't exist.

        Base template files (soul.md, bootstrap.md, etc.) are copied by
        _setup_workspace() in __main__.py before any agent runs.
        """
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "skills").mkdir(parents=True, exist_ok=True)

    # ── Soul Files ──

    def load_soul(self, role: str) -> str:
        """Load the soul file for a role from workspace/{role}/soul.md."""
        soul_path = self.workspace_dir / role / "soul.md"
        if soul_path.exists():
            return soul_path.read_text()
        return f"You are the {role} agent."

    def load_curated_memory(self, role: str) -> str:
        """Load the MEMORY.md curated long-term memory for a role."""
        path = self.workspace_dir / role / "MEMORY.md"
        return path.read_text() if path.exists() else ""

    def get_heartbeat_instructions(self) -> str:
        """Load the manager's heartbeat task instructions."""
        path = self.workspace_dir / "manager" / "heartbeat.md"
        return path.read_text() if path.exists() else ""

    def get_recent_memory(self, days: int = 3) -> str:
        """Return concatenated memory files for today and past (days-1) days."""
        parts = []
        for i in range(days):
            day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
            path = self.memories_dir / f"memory-{day}.md"
            if path.exists():
                content = path.read_text().strip()
                if content:
                    parts.append(content)
        return "\n\n---\n\n".join(parts)

    # ── Short-term Memory (delegates to DB) ──

    def get_short_term(self, db, task_id, role: str | None = None,
                       limit: int = 10) -> list[dict]:
        return db.get_short_term(task_id, role, limit)

    def record_turn(self, db, task_id, role: str, turn_type: str, content: str):
        turns = db.get_short_term(task_id, role)
        turn_number = len(turns) + 1
        db.record_turn(task_id, role, turn_type, content, turn_number)

    # ── Long-term Memory (FAISS + fastembed) ──

    def _get_embedder(self):
        """Lazy-load the fastembed model."""
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
                self._embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
                logger.info("Loaded fastembed model: BAAI/bge-small-en-v1.5")
            except ImportError:
                logger.warning("fastembed not installed, long-term memory disabled")
                return None
        return self._embedder

    def _get_index(self, db):
        """Load or create the FAISS index."""
        if self._index is not None:
            return self._index

        try:
            import faiss
        except ImportError:
            logger.warning("faiss-cpu not installed, long-term memory disabled")
            return None

        faiss_path = Path(self.faiss_path)
        if faiss_path.exists():
            self._index = faiss.read_index(str(faiss_path))
            # Rebuild ID map from DB
            all_memories = db.get_all_memories()
            self._id_map = [m["id"] for m in all_memories]
            logger.info(f"Loaded FAISS index with {self._index.ntotal} vectors")
        else:
            # Create new index (384-dim for bge-small-en-v1.5)
            self._index = faiss.IndexFlatL2(384)
            self._id_map = []
            logger.info("Created new FAISS index")

        return self._index

    def _save_index(self):
        """Persist the FAISS index to disk."""
        if self._index is not None:
            try:
                import faiss
                Path(self.faiss_path).parent.mkdir(parents=True, exist_ok=True)
                faiss.write_index(self._index, str(self.faiss_path))
            except Exception as e:
                logger.error(f"Failed to save FAISS index: {e}")

    def remember(self, db, role: str, content: str, category: str = "lesson",
                 task_id=None, confidence: float = 1.0):
        """Store a memory: embed with fastembed, store vector in FAISS, text in SQLite."""
        embedder = self._get_embedder()
        index = self._get_index(db)

        # Always store in SQLite
        memory_id = db.store_memory(role, content, category, task_id, confidence)

        if embedder is None or index is None:
            return memory_id

        # Embed and store in FAISS
        try:
            embeddings = list(embedder.embed([content]))
            vector = np.array(embeddings[0], dtype=np.float32).reshape(1, -1)
            index.add(vector)
            self._id_map.append(memory_id)
            self._save_index()
            logger.debug(f"Stored memory #{memory_id} in FAISS (total: {index.ntotal})")
        except Exception as e:
            logger.error(f"Failed to embed memory: {e}")

        return memory_id

    def recall(self, db, role: str, query: str, top_k: int = 5) -> list[dict]:
        """Recall relevant memories by semantic search."""
        embedder = self._get_embedder()
        index = self._get_index(db)

        if embedder is None or index is None or index.ntotal == 0:
            return []

        try:
            embeddings = list(embedder.embed([query]))
            vector = np.array(embeddings[0], dtype=np.float32).reshape(1, -1)
            distances, indices = index.search(vector, min(top_k, index.ntotal))

            results = []
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self._id_map):
                    continue
                memory_id = self._id_map[idx]
                memory = db.get_memory_by_id(memory_id)
                if memory and (role is None or memory["role"] == role):
                    memory["distance"] = float(distances[0][i])
                    results.append(memory)

            return results
        except Exception as e:
            logger.error(f"Failed to recall memories: {e}")
            return []

    # ── Context Building ──

    def load_skills(self) -> str:
        """Load all skill files. Core skills (macgent/skills/) first, then learned (workspace/skills/).

        Core skills = shipped with the package (browser, macos, communication) — always present.
        Learned skills = written by the agent during bootstrap (notion, etc.).
        """
        parts = []
        # 1. Core skills (fixed, inside the package)
        if self._CORE_SKILLS_DIR.exists():
            for path in sorted(self._CORE_SKILLS_DIR.glob("*.md")):
                content = path.read_text().strip()
                if content:
                    parts.append(content)
        # 2. Learned skills (workspace/skills/ — agent writes these)
        learned_dir = self.workspace_dir / "skills"
        if learned_dir.exists():
            for path in sorted(learned_dir.glob("*.md")):
                content = path.read_text().strip()
                if content:
                    parts.append(content)
        return "\n\n---\n\n".join(parts)

    def build_context(self, db, role: str, task_id=None,
                      task_description: str = "") -> str:
        """Build full context: soul + skills + curated memory + recent daily logs + semantic recall."""
        parts = []

        # 1. Soul
        soul = self.load_soul(role)
        if soul:
            parts.append(soul)

        # 2. Shared skills (souls/skills/*.md) — always loaded
        skills = self.load_skills()
        if skills:
            parts.append("\n---\n# Skills Reference\n\n" + skills)

        # 3. Curated long-term memory (MEMORY.md)
        curated = self.load_curated_memory(role)
        if curated:
            parts.append("\n## Curated Memory (MEMORY.md)\n" + curated)

        # 4. Recent daily logs (today + last 2 days)
        recent = self.get_recent_memory(days=3)
        if recent:
            parts.append("\n## Recent Daily Logs\n" + recent)

        # 5. Short-term memory (recent turns for this task)
        if task_id:
            turns = self.get_short_term(db, task_id, limit=10)
            if turns:
                parts.append("\n## Recent Task History")
                for t in turns:
                    parts.append(f"[{t['role']}] ({t['type']}): {t['content']}")

        # 6. Long-term memories (semantic recall)
        if task_description:
            memories = self.recall(db, role, task_description, top_k=5)
            if memories:
                parts.append("\n## Relevant Past Experiences")
                for m in memories:
                    parts.append(f"- [{m['category']}] {m['content']}")

        return "\n".join(parts)

    # ── Daily Memory Logs ──

    def write_daily_log(self, db, content: str, role: str = "manager"):
        """Append a timestamped entry to today's memory file and embed it."""
        today = datetime.date.today().isoformat()
        path = self.memories_dir / f"memory-{today}.md"
        now = datetime.datetime.now().strftime("%H:%M")

        if not path.exists():
            path.write_text(f"# Memory Log — {today}\n")

        entry = f"\n## {now}\n{content}\n"
        with open(path, "a") as f:
            f.write(entry)

        # Embed for semantic recall
        self.remember(db, role, content, category="daily_log")
        logger.debug(f"Wrote daily log entry for {today}")

    def get_today_memory(self) -> str:
        """Return today's memory file content, or empty string if none yet."""
        today = datetime.date.today().isoformat()
        path = self.memories_dir / f"memory-{today}.md"
        return path.read_text() if path.exists() else ""

    def embed_past_logs(self, db, days: int = 3):
        """Embed recent daily log files into FAISS (call once on startup)."""
        for i in range(days):
            day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
            path = self.memories_dir / f"memory-{day}.md"
            if path.exists():
                content = path.read_text().strip()
                if content:
                    self.remember(db, "manager", content, category="daily_log")
        logger.info(f"Embedded past {days} days of memory logs")
