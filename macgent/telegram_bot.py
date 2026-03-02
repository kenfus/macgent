"""Telegram bot integration for macgent multi-agent system."""

import logging
import httpx
import asyncio
import mimetypes
from datetime import datetime
from pathlib import Path

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_START = 2.0
_BACKOFF_MULT = 2.0

from macgent.config import Config
from macgent import message_bus

logger = logging.getLogger("macgent.telegram")


class TelegramBot:
    def __init__(self, config: Config):
        self.config = config
        self.token = config.telegram_bot_token
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

    def _workspace_root(self) -> Path:
        root = Path(getattr(self.config, "workspace_dir", "workspace"))
        return root.resolve()

    def _inbox_dir(self) -> Path:
        folder = self._workspace_root() / "agent" / "inbox" / "telegram"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    async def _download_file(self, file_id: str) -> tuple[str, str] | None:
        """Download a Telegram file and return (relative_path, media_type)."""
        meta = await self._api_call("getFile", file_id=file_id)
        remote_path = str(meta.get("file_path", "")).strip()
        if not remote_path:
            logger.warning("Telegram getFile returned no file_path for file_id=%s", file_id)
            return None

        ext = Path(remote_path).suffix or ".bin"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        local_name = f"{stamp}_{file_id[:16]}{ext}"
        abs_path = self._inbox_dir() / local_name
        file_url = f"https://api.telegram.org/file/bot{self.token}/{remote_path}"

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.get(file_url)
                resp.raise_for_status()
            abs_path.write_bytes(resp.content)
        except Exception as e:
            logger.error("Failed to download Telegram file %s: %s", file_id, e)
            return None

        media_type = mimetypes.guess_type(abs_path.name)[0] or "application/octet-stream"
        rel_path = abs_path.relative_to(self._workspace_root()).as_posix()
        return rel_path, media_type

    async def _collect_attachments(self, message: dict) -> list[dict]:
        """Collect downloadable image attachments from Telegram message payload."""
        attachments: list[dict] = []

        photos = message.get("photo") or []
        if photos:
            best = max(
                photos,
                key=lambda p: int(p.get("file_size", 0) or 0) or int(p.get("width", 0)) * int(p.get("height", 0)),
            )
            file_id = str(best.get("file_id", "")).strip()
            if file_id:
                downloaded = await self._download_file(file_id)
                if downloaded:
                    rel_path, media_type = downloaded
                    attachments.append(
                        {"type": "image", "path": rel_path, "media_type": media_type, "source": "telegram_photo"}
                    )

        doc = message.get("document") or {}
        doc_file_id = str(doc.get("file_id", "")).strip()
        doc_mime = str(doc.get("mime_type", "")).strip().lower()
        doc_name = str(doc.get("file_name", "")).strip().lower()
        is_image_doc = doc_mime.startswith("image/") or doc_name.endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
        )
        if doc_file_id and is_image_doc:
            downloaded = await self._download_file(doc_file_id)
            if downloaded:
                rel_path, media_type = downloaded
                attachments.append(
                    {"type": "image", "path": rel_path, "media_type": media_type, "source": "telegram_document"}
                )

        return attachments

    async def _api_call(self, method: str, **kwargs) -> dict:
        """Make API call to Telegram Bot API with retry/backoff on transient errors."""
        url = f"{self.api_base}/{method}"
        poll_timeout = kwargs.get("timeout", 0)
        http_timeout = max(30, poll_timeout + 10)
        backoff = _BACKOFF_START
        for attempt in range(1, _MAX_RETRIES + 2):
            try:
                async with httpx.AsyncClient(timeout=http_timeout) as client:
                    response = await client.post(url, json=kwargs)
                    if response.status_code in _RETRY_STATUSES and attempt <= _MAX_RETRIES:
                        logger.info("Telegram API %s status=%d, retrying in %.1fs (attempt %d/%d)",
                                    method, response.status_code, backoff, attempt, _MAX_RETRIES)
                        await asyncio.sleep(backoff)
                        backoff *= _BACKOFF_MULT
                        continue
                    result = response.json()
                    if not result.get("ok"):
                        logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
                    return result.get("result", {})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt <= _MAX_RETRIES:
                    logger.info("Telegram API %s network error, retrying in %.1fs: %s", method, backoff, e)
                    await asyncio.sleep(backoff)
                    backoff *= _BACKOFF_MULT
                else:
                    raise
        return {}

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
        """Route incoming Telegram message to the agent for LLM enhancement."""
        text = message.get("text", "").strip()
        caption = message.get("caption", "").strip()
        attachments = await self._collect_attachments(message)
        has_photo = bool(message.get("photo"))
        has_document = "document" in message
        has_video = "video" in message
        has_voice = "voice" in message
        has_audio = "audio" in message
        user_id = message["from"]["id"]
        user_name = message["from"].get("first_name", "User")

        # Telegram media messages usually come as caption + media payload
        # (not in `text`). Convert common content types to queueable text.
        content = text
        if not content and caption:
            content = caption
        if not content and attachments:
            content = "[image]"
        if not content and has_photo:
            content = "[photo]"
        if not content and has_document:
            content = "[document]"
        if not content and has_video:
            content = "[video]"
        if not content and has_voice:
            content = "[voice]"
        if not content and has_audio:
            content = "[audio]"

        if not content:
            logger.info(
                "Ignoring unsupported Telegram message from %s (ID %s): keys=%s",
                user_name,
                user_id,
                ",".join(sorted(message.keys())),
            )
            return

        logger.info(f"Active task from {user_name} (ID {user_id}): {content[:80]}")

        # Store as CEO → agent message for FIFO processing.
        message_bus.enqueue_message(
            "ceo",
            "agent",
            task_id=None,
            content=content,
            attachments=attachments,
        )

        # Wake the agent loop immediately for active task processing.
        self._wake_manager()

        # Brief acknowledgment — agent will send the real response via Telegram
        logger.info("Queued CEO message for agent processing (attachments=%d)", len(attachments))

    def _wake_manager(self) -> None:
        """Signal the manager to wake up and process this task immediately."""
        message_bus.request_wake()
        logger.info("Manager wake signal sent")

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
    """Send a plain text message to the configured chat with retry/backoff."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {"chat_id": config.telegram_chat_id, "text": text}
    backoff = _BACKOFF_START
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload)
                if response.status_code in _RETRY_STATUSES and attempt <= _MAX_RETRIES:
                    logger.info("send_text status=%d, retrying in %.1fs (attempt %d/%d)",
                                response.status_code, backoff, attempt, _MAX_RETRIES)
                    await asyncio.sleep(backoff)
                    backoff *= _BACKOFF_MULT
                    continue
                return
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            if attempt <= _MAX_RETRIES:
                logger.info("send_text network error, retrying in %.1fs: %s", backoff, e)
                await asyncio.sleep(backoff)
                backoff *= _BACKOFF_MULT
            else:
                raise


def sync_send_message(config: Config, text: str) -> None:
    """Synchronous helper to send a plain text Telegram message."""
    try:
        asyncio.run(_send_text(config, text))
    except Exception as e:
        logger.debug(f"sync_send_message failed: {e}")
