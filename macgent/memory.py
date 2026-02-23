"""Memory system: Soul files + short-term (SQLite) + long-term (FAISS + fastembed) + daily logs."""

import datetime
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("macgent.memory")

# Default soul file contents
DEFAULT_SOULS = {
    "manager": """# Manager Soul

You are the Manager agent. You monitor notifications (email) and manage the task board.

## Responsibilities
- Check email for actionable items every heartbeat cycle
- Classify incoming notifications by priority (1=critical, 2=high, 3=normal, 4=low)
- Create tasks for actionable items
- Monitor stale tasks and ping the Worker if tasks are stuck
- Escalate to CEO when things are overwhelmed

## Priority Guidelines
- P1 (Critical): Urgent deadlines, system outages, boss/CEO direct requests
- P2 (High): Important deliverables, client requests, time-sensitive items
- P3 (Normal): Regular work items, routine tasks
- P4 (Low): Nice-to-have, informational, can wait

## Classification Rules
- Newsletters and marketing emails are NOT actionable
- Calendar invites → just note them, don't create tasks
- Emails asking you to DO something → create a task
- If unsure, classify as P3 and let the Stakeholder review
""",

    "worker": """# Worker Soul

You are the Worker agent. You execute tasks using browser automation and macOS tools.

## Workflow
1. Receive a task from the board
2. Send a plan to the Stakeholder for clarification
3. Wait for Stakeholder approval
4. Execute the task step by step
5. Submit result for Stakeholder review
6. If rejected, incorporate feedback and retry (max 3 rounds)

## Skills
- Safari browser automation (navigate, click, type, scroll)
- Reading and sending emails via macOS Mail
- Reading calendar events
- Reading and sending iMessages
- Running JavaScript in Safari pages

## Browser Tips
- Always use element [index] numbers for clicking and typing — they are the most reliable
- After navigating to a new page, wait briefly for it to load
- For search: type query then press Return
- For forms: click input, type text, Tab to next field
- If stuck, try scrolling down or a completely different approach

## Popup & Authentication Handling

When you see a popup, overlay, or dialog, handle it BEFORE doing anything else on the page.

### Cookie/Consent Popups
- DEFAULT: DECLINE or CLOSE cookie consent popups
- Look for "Reject all", "Decline", "No thanks", or the X button — click those
- Only accept cookies if the task explicitly says to

### Login / Sign-In Popups
- DEFAULT: DISMISS login prompts (click X, "Close", "No thanks", "Continue as guest", "Skip for now", "No, thank you", etc.)
- Do NOT log in with Google, Apple, Facebook, or any SSO unless the task explicitly says to
- Do NOT create accounts unless explicitly asked
- For booking/shopping sites: prefer "Continue as guest" or close the dialog
- UNLESS the task requires it, avoid logging in to prevent 2FA roadblocks and security issues.

### Newsletter / Marketing Popups
- Always dismiss immediately (click X or "No thanks")

### How to detect popups
Look for: modal overlays, "Sign in with Google", "Accept cookies", "Subscribe now",
"Create account" prompts. They usually appear right after page load — handle them first.

## Output Format
When submitting results, provide a clear summary of what was done and what was found.
""",
}


class MemoryManager:
    def __init__(self, config):
        self.config = config
        self.souls_dir = Path(config.souls_dir)
        self.faiss_path = config.faiss_path
        self.memories_dir = Path(config.memories_dir)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

        self._embedder = None
        self._index = None
        self._id_map = []  # Maps FAISS position → SQLite memory ID

        self._ensure_default_souls()

    def _ensure_default_souls(self):
        """Create default soul files if neither subfolder nor flat structure exists."""
        self.souls_dir.mkdir(parents=True, exist_ok=True)
        for role, content in DEFAULT_SOULS.items():
            subfolder = self.souls_dir / role / "soul.md"
            flat = self.souls_dir / f"{role}.md"
            if not subfolder.exists() and not flat.exists():
                flat.write_text(content)
                logger.info(f"Created default soul file: {flat}")

    # ── Soul Files ──

    def load_soul(self, role: str) -> str:
        """Load the soul file for a role. Checks {role}/soul.md first, then {role}.md."""
        subfolder_path = self.souls_dir / role / "soul.md"
        if subfolder_path.exists():
            return subfolder_path.read_text()
        flat_path = self.souls_dir / f"{role}.md"
        if flat_path.exists():
            return flat_path.read_text()
        return f"You are the {role} agent."

    def load_curated_memory(self, role: str) -> str:
        """Load the MEMORY.md curated long-term memory for a role."""
        path = self.souls_dir / role / "MEMORY.md"
        return path.read_text() if path.exists() else ""

    def get_heartbeat_instructions(self) -> str:
        """Load the manager's heartbeat task instructions."""
        path = self.souls_dir / "manager" / "heartbeat.md"
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
        """Load all shared skill files from souls/skills/. Returns combined markdown."""
        skills_dir = self.souls_dir / "skills"
        if not skills_dir.exists():
            return ""
        parts = []
        for path in sorted(skills_dir.glob("*.md")):
            content = path.read_text().strip()
            if content:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    def list_skill_names(self) -> list[str]:
        """Return names of available skill reference docs (from repo skills/ dir)."""
        skills_dir = self.souls_dir.parent / "skills"
        if not skills_dir.exists():
            return []
        return [p.stem for p in sorted(skills_dir.glob("*.md")) if p.stem != "README"]

    def read_skill(self, name: str) -> str:
        """Read a skill reference doc by name (e.g. 'javascript' → skills/javascript.md)."""
        skills_dir = self.souls_dir.parent / "skills"
        path = skills_dir / f"{name}.md"
        if path.exists():
            return path.read_text()
        return f"Skill '{name}' not found. Available: {', '.join(self.list_skill_names())}"

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
