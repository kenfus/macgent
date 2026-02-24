"""
Show Telegram/CEO message history for the MacGent bot.

Reads from two sources:
  1. macgent DB (messages already processed by the bot — most reliable)
  2. Telegram getUpdates API (only unprocessed/pending updates)

Usage:
    uv run scripts/tg_history.py             # show DB history
    uv run scripts/tg_history.py --pending   # also check unprocessed Telegram updates
    uv run scripts/tg_history.py --poll      # live-poll Telegram for new messages
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))


def load_env():
    try:
        from dotenv import load_dotenv, find_dotenv
        load_dotenv(find_dotenv(usecwd=True) or root / ".env")
    except ImportError:
        pass
    import os
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    db_path = os.getenv("MACGENT_DB_PATH", str(Path.home() / ".macgent" / "macgent.db"))
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)
    return token, chat_id, db_path


def show_db_history(db_path: str, limit: int = 50):
    """Show messages stored in the macgent DB (already processed)."""
    if not Path(db_path).exists():
        print(f"(DB not found at {db_path})")
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT from_role, to_role, content, created_at FROM messages "
        "ORDER BY created_at ASC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    if not rows:
        print("(No messages in DB yet)")
        return

    print(f"=== DB History ({len(rows)} messages) ===\n")
    for r in rows:
        tag = "[CEO]" if r["from_role"] == "ceo" else f"[{r['from_role'].upper()}]"
        # Truncate long messages
        text = r["content"]
        if len(text) > 200:
            text = text[:200] + "…"
        print(f"{r['created_at']}  {tag} → {r['to_role']}: {text}")
    print()


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def show_pending(token: str, chat_id: str):
    """Show unprocessed Telegram updates (not yet seen by the bot)."""
    import httpx
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json={"limit": 100, "timeout": 0})
        data = r.json()

    updates = data.get("result", []) if data.get("ok") else []
    if not updates:
        print("=== Pending Telegram Updates: none ===\n")
        return

    print(f"=== Pending Telegram Updates ({len(updates)}) ===\n")
    for u in updates:
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        cid = str(msg.get("chat", {}).get("id", ""))
        if chat_id and cid != chat_id:
            continue
        sender = msg.get("from", {})
        name = (sender.get("first_name", "") + " " + sender.get("last_name", "")).strip()
        name = name or sender.get("username", "unknown")
        is_bot = sender.get("is_bot", False)
        tag = "[BOT]" if is_bot else "[CEO]"
        ts = fmt_ts(msg.get("date", 0))
        text = msg.get("text", "(no text)")
        print(f"{ts}  {tag} {name}: {text}")
    print()


async def live_poll(token: str, chat_id: str):
    """Keep polling Telegram for new messages in real time."""
    import httpx
    print("Live polling (Ctrl+C to stop)...\n")
    offset = 0
    while True:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        async with httpx.AsyncClient(timeout=40) as client:
            try:
                r = await client.post(url, json={"offset": offset, "limit": 100, "timeout": 30})
                data = r.json()
                updates = data.get("result", []) if data.get("ok") else []
            except Exception as e:
                print(f"Poll error: {e}")
                await asyncio.sleep(2)
                continue
        for u in updates:
            msg = u.get("message") or u.get("edited_message")
            if msg:
                cid = str(msg.get("chat", {}).get("id", ""))
                if not chat_id or cid == chat_id:
                    sender = msg.get("from", {})
                    name = (sender.get("first_name", "") + " " + sender.get("last_name", "")).strip()
                    is_bot = sender.get("is_bot", False)
                    tag = "[BOT]" if is_bot else "[CEO]"
                    ts = fmt_ts(msg.get("date", 0))
                    print(f"{ts}  {tag} {name}: {msg.get('text', '(no text)')}")
            offset = u["update_id"] + 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show MacGent Telegram message history")
    parser.add_argument("--limit", type=int, default=50, help="Max DB messages to show (default 50)")
    parser.add_argument("--pending", action="store_true", help="Also show unprocessed Telegram updates")
    parser.add_argument("--poll", action="store_true", help="Live-poll Telegram for new messages")
    args = parser.parse_args()

    token, chat_id, db_path = load_env()

    if args.poll:
        asyncio.run(live_poll(token, chat_id))
    else:
        show_db_history(db_path, args.limit)
        if args.pending:
            asyncio.run(show_pending(token, chat_id))
