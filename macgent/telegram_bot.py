"""Telegram bot integration for macgent multi-agent system."""

import logging
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

    async def process_message(self, message: dict) -> None:
        """Route incoming Telegram message to the manager for LLM enhancement."""
        text = message.get("text", "").strip()
        chat_id = str(message["chat"]["id"])
        user_id = message["from"]["id"]
        user_name = message["from"].get("first_name", "User")

        if not text:
            return

        logger.info(f"Active task from {user_name} (ID {user_id}): {text[:80]}")

        # Store as CEO → manager message so manager's LLM flow handles it:
        # enhance → clarify if needed → create Notion task as "Ready" → spawn worker
        self.db.send_message("ceo", "manager", task_id=None, content=text)

        # Wake the manager immediately for active task processing
        self._wake_manager()

        # Brief acknowledgment — manager will send the real response via Telegram
        await self.send_message(chat_id, "On it! I'll get back to you shortly.")
        logger.info(f"Queued CEO message for manager processing")

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


async def _send_text(config: Config, text: str) -> None:
    """Send a plain text message to the configured chat."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": config.telegram_chat_id, "text": text, "parse_mode": "Markdown"})


def sync_send_message(config: Config, text: str) -> None:
    """Synchronous helper to send a plain text Telegram message."""
    try:
        asyncio.run(_send_text(config, text))
    except Exception as e:
        logger.debug(f"sync_send_message failed: {e}")
