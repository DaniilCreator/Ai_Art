from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    message_id: int | None
    error: str | None


class Publisher:
    def __init__(self, bot: Bot, channel_id: str, send_as: str = "photo"):
        self.bot = bot
        self.channel_id = channel_id
        self.send_as = send_as

    async def publish(self, file_path: str, caption: str = "") -> PublishResult:
        """Publish image to channel.

        send_as:
          - "photo" (default recommended): sends as Photo
          - "document": sends as Document
        """
        try:
            if (self.send_as or "photo").lower() == "document":
                doc = FSInputFile(file_path)
                msg = await self.bot.send_document(chat_id=self.channel_id, document=doc, caption=caption or "")
            else:
                photo = FSInputFile(file_path)
                msg = await self.bot.send_photo(chat_id=self.channel_id, photo=photo, caption=caption or "")

            return PublishResult(ok=True, message_id=getattr(msg, "message_id", None), error=None)
        except Exception as e:
            return PublishResult(ok=False, message_id=None, error=str(e))
