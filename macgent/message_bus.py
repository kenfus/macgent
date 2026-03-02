"""In-memory FIFO message bus and wake signal for manager/telegram routing."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Any

_messages: deque[dict] = deque()
_lock = Lock()
_wake_event = Event()
_next_id = 1


def enqueue_message(
    from_role: str,
    to_role: str,
    task_id: str | None,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict:
    """Append one message to the in-memory FIFO queue."""
    global _next_id
    with _lock:
        item = {
            "id": _next_id,
            "from_role": from_role,
            "to_role": to_role,
            "task_id": task_id,
            "content": content,
            "attachments": list(attachments or []),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _next_id += 1
        _messages.append(item)
        return dict(item)


def dequeue_message(
    to_role: str,
    task_id: str | None = None,
    from_role: str | None = None,
) -> dict | None:
    """Pop the first matching message (FIFO by insertion order)."""
    with _lock:
        kept: deque[dict] = deque()
        found: dict | None = None
        while _messages:
            msg = _messages.popleft()
            matches = msg.get("to_role") == to_role
            if task_id is not None:
                matches = matches and msg.get("task_id") == task_id
            if from_role is not None:
                matches = matches and msg.get("from_role") == from_role

            if matches and found is None:
                found = msg
            else:
                kept.append(msg)
        _messages.extend(kept)
        return dict(found) if found else None


def has_pending_messages(to_role: str, from_role: str | None = None) -> bool:
    """Return True if there is at least one matching message without consuming it."""
    with _lock:
        for msg in _messages:
            if msg.get("to_role") == to_role:
                if from_role is None or msg.get("from_role") == from_role:
                    return True
    return False


def request_wake() -> None:
    _wake_event.set()


def clear_wake() -> None:
    _wake_event.clear()


def should_wake() -> bool:
    return _wake_event.is_set()
