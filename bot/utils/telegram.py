"""Небольшие обёртки над Telegram API."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


def _is_not_modified(error: TelegramBadRequest) -> bool:
    return "message is not modified" in str(error)


def callback_message(callback: CallbackQuery) -> Message | None:
    """Сообщение под кнопкой, если оно ещё доступно боту (не старше 48 часов)."""
    return callback.message if isinstance(callback.message, Message) else None


async def edit_text(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if not _is_not_modified(e):
            raise


async def edit_markup(message: Message, reply_markup: InlineKeyboardMarkup | None) -> None:
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if not _is_not_modified(e):
            raise
