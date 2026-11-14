"""Middleware: сессия БД на каждый апдейт и текущий пользователь."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.repositories import UserRepo


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию на время обработки апдейта и коммитит её, если хендлер не упал."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            result = await handler(event, data)
            await session.commit()
            return result


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя при первом обращении и обновляет дату активности.

    Должен стоять после DbSessionMiddleware. Кладёт в data ключ `user`.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        session: AsyncSession = data["session"]
        data["user"] = await UserRepo(session).upsert(
            user_id=tg_user.id, full_name=tg_user.full_name, username=tg_user.username
        )
        return await handler(event, data)
