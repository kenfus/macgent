"""SQLite database layer for macgent multi-agent system."""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


class DB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'ceo',
                priority INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                review_note TEXT,
                escalation TEXT,
                ping_pong_round INTEGER NOT NULL DEFAULT 0,
                notion_page_id TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_role TEXT NOT NULL,
                to_role TEXT NOT NULL,
                task_id INTEGER,
                content TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT,
                task_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS monitor_state (
                source TEXT PRIMARY KEY,
                last_check TEXT,
                metadata TEXT
            );

        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Run any pending schema migrations."""
        # Tasks table kept for backwards compat but no longer used.
        # All task CRUD goes through Notion (notion_actions.py).
        pass

    # ── Messages ──
    # Note: task_id in messages now stores Notion page_id (string).
    # SQLite is dynamically typed so this works without schema changes.

    def send_message(self, from_role: str, to_role: str, task_id: int | None,
                     content: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (from_role, to_role, task_id, content) VALUES (?, ?, ?, ?)",
            (from_role, to_role, task_id, content),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_unread_messages(self, to_role: str, task_id: int | None = None) -> list[dict]:
        if task_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE to_role = ? AND task_id = ? AND read = 0 ORDER BY created_at",
                (to_role, task_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE to_role = ? AND read = 0 ORDER BY created_at",
                (to_role,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_messages_read(self, to_role: str, task_id: int | None = None):
        if task_id is not None:
            self.conn.execute(
                "UPDATE messages SET read = 1 WHERE to_role = ? AND task_id = ?",
                (to_role, task_id),
            )
        else:
            self.conn.execute(
                "UPDATE messages SET read = 1 WHERE to_role = ?",
                (to_role,),
            )
        self.conn.commit()

    def get_unread_messages_for_task(self, task_id: int, from_role: str | None = None) -> list[dict]:
        if from_role:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE task_id = ? AND from_role = ? AND read = 0 ORDER BY created_at",
                (task_id, from_role),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE task_id = ? AND read = 0 ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_task_messages(self, task_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Agent Log ──

    def log(self, role: str, action: str, detail: str = "", task_id: int | None = None):
        self.conn.execute(
            "INSERT INTO agent_log (role, action, detail, task_id) VALUES (?, ?, ?, ?)",
            (role, action, detail, task_id),
        )
        self.conn.commit()

    def get_task_recent_activity(self, task_id: int, limit: int = 5) -> list[dict]:
        """Get recent agent_log entries for a task (for manager progress peeks)."""
        rows = self.conn.execute(
            "SELECT * FROM agent_log WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_log(self, limit: int = 20, role: str | None = None) -> list[dict]:
        if role:
            rows = self.conn.execute(
                "SELECT * FROM agent_log WHERE role = ? ORDER BY created_at DESC LIMIT ?",
                (role, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM agent_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Monitor State ──

    def get_monitor_state(self, source: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM monitor_state WHERE source = ?", (source,),
        ).fetchone()
        return dict(row) if row else None

    def set_monitor_state(self, source: str, last_check: str, metadata: str = ""):
        self.conn.execute(
            """INSERT INTO monitor_state (source, last_check, metadata)
               VALUES (?, ?, ?)
               ON CONFLICT(source) DO UPDATE SET last_check = ?, metadata = ?""",
            (source, last_check, metadata, last_check, metadata),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
