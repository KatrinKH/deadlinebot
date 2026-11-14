"""Рассылка сообщений подписчикам предмета."""

import asyncio
import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

logger = logging.getLogger(__name__)

# Telegram ограничивает рассылку ~30 сообщениями в секунду — держимся с запасом
SEND_INTERVAL = 0.05


async def broadcast(bot: Bot, user_ids: Iterable[int], text: str) -> int:
    """Отправляет сообщение каждому пользователю. Возвращает число доставленных."""
    sent = 0
    for user_id in user_ids:
        try:
            await _send(bot, user_id, text)
            sent += 1
        except TelegramForbiddenError:
            logger.info("User %s blocked the bot", user_id)
        except TelegramAPIError:
            logger.exception("Failed to send message to %s", user_id)
        await asyncio.sleep(SEND_INTERVAL)
    return sent


async def _send(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.send_message(user_id, text)
