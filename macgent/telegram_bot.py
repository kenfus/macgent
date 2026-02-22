"""Telegram bot integration for macgent multi-agent system."""

import logging
import json
from typing import Optional
from datetime import datetime, timezone
import httpx
import asyncio

from macgent.config import Config
from macgent.db import DB

logger = logging.getLogger("macgent.telegram")


class TelegramBot:
    def __init__(self, config: Config, db: DB):
        self.config = config
        self.db = db
        self.token = config.telegram_bot_token
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

    async def _api_call(self, method: str, **kwargs) -> dict:
        """Make API call to Telegram Bot API."""
        url = f"{self.api_base}/{method}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=kwargs)
            result = response.json()
            if not result.get("ok"):
                logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
            return result.get("result", {})

    async def send_message(self, chat_id: str, text: str) -> bool:
        """Send a message via Telegram."""
        try:
            result = await self._api_call("sendMessage", chat_id=chat_id, text=text)
            logger.info(f"Sent message to {chat_id}: {text[:50]}")
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def get_updates(self, timeout: int = 30) -> list:
        """Get updates from Telegram using long polling."""
        try:
            updates = await self._api_call("getUpdates", offset=self.offset, timeout=timeout)
            return updates if isinstance(updates, list) else []
        except Exception as e:
            logger.error(f"Failed to get updates: {e}")
            return []

    async def process_message(self, message: dict) -> Optional[int]:
        """Process incoming Telegram message and create a task."""
        text = message.get("text", "").strip()
        chat_id = str(message["chat"]["id"])
        user_id = message["from"]["id"]
        user_name = message["from"].get("first_name", "User")

        if not text:
            return None

        logger.info(f"Message from {user_name} (ID {user_id}): {text[:80]}")

        # Create task
        title = text[:80]
        description = text
        task_id = self.db.create_task(
            title=title,
            description=description,
            source=f"telegram_{user_id}",
            priority=2,
        )

        # Store chat_id and user_id in task metadata for responses
        self.db.conn.execute(
            "UPDATE tasks SET review_note = ? WHERE id = ?",
            (json.dumps({"chat_id": chat_id, "user_id": user_id, "user_name": user_name}), task_id)
        )
        self.db.conn.commit()

        # Wake the manager for immediate processing
        self._wake_manager()

        # Send acknowledgment
        await self.send_message(chat_id, f"✓ Task #{task_id} received: {title}\nProcessing...")

        logger.info(f"Created task #{task_id} from Telegram message")
        return task_id

    def _wake_manager(self) -> None:
        """Signal the manager to wake up and process this task immediately."""
        try:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).isoformat()
            self.db.conn.execute(
                "INSERT OR REPLACE INTO monitor_state (source, last_check, metadata) VALUES (?, ?, ?)",
                ("_wake_request", timestamp, "Woken by Telegram message")
            )
            self.db.conn.commit()
            logger.info("Manager wake signal sent")
        except Exception as e:
            logger.error(f"Failed to send wake signal: {e}")

    async def handle_callback_query(self, query: dict) -> None:
        """Handle inline buttons/callbacks from Telegram."""
        query_id = query["id"]
        callback_data = query.get("data", "")
        logger.debug(f"Callback query: {callback_data}")

        # Acknowledge the callback
        try:
            await self._api_call("answerCallbackQuery", callback_query_id=query_id)
        except Exception as e:
            logger.error(f"Failed to answer callback: {e}")

    async def run_polling(self):
        """Main polling loop for Telegram updates."""
        logger.info("Starting Telegram bot polling...")
        print(f"Telegram bot listening (chat ID: {self.config.telegram_chat_id})")

        try:
            while True:
                updates = await self.get_updates(timeout=30)

                for update in updates:
                    self.offset = update["update_id"] + 1

                    # Handle text messages
                    if "message" in update:
                        message = update["message"]
                        await self.process_message(message)

                    # Handle callback queries
                    elif "callback_query" in update:
                        query = update["callback_query"]
                        await self.handle_callback_query(query)

                # Small sleep to avoid busy waiting
                await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("Telegram bot polling stopped.")
        except Exception as e:
            logger.error(f"Telegram polling error: {e}")
            raise


async def notify_task_update(config: Config, db: DB, task_id: int) -> None:
    """Send task update notification via Telegram."""
    try:
        task = db.get_task(task_id)
        if not task:
            return

        # Try to parse chat_id from review_note
        chat_id = None
        if task.get("review_note"):
            try:
                metadata = json.loads(task["review_note"])
                chat_id = metadata.get("chat_id")
            except (json.JSONDecodeError, TypeError):
                pass

        if not chat_id:
            return

        bot = TelegramBot(config, db)
        status_emoji = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "failed": "❌",
            "escalated": "⚠️",
            "review": "👀",
        }.get(task["status"], "•")

        message = f"{status_emoji} Task #{task_id}\nStatus: {task['status']}"
        if task.get("result"):
            message += f"\n\nResult: {task['result'][:200]}"
        if task.get("review_note") and task["status"] != "pending":
            try:
                metadata = json.loads(task["review_note"])
                if "review_feedback" in metadata:
                    message += f"\n\nFeedback: {metadata['review_feedback']}"
            except (json.JSONDecodeError, TypeError):
                pass

        await bot.send_message(chat_id, message)
    except Exception as e:
        logger.error(f"Failed to send task update: {e}")


def sync_notify_task_update(config: Config, db: DB, task_id: int) -> None:
    """Synchronous wrapper for notify_task_update."""
    try:
        asyncio.run(notify_task_update(config, db, task_id))
    except Exception as e:
        logger.error(f"Failed to notify task update: {e}")
