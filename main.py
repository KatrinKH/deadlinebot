"""Точка входа: миграции → загрузка seed.yaml → запуск бота."""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from bot import texts
from bot.config import Settings, get_settings
from bot.db.seed import apply_seed, load_seed_file
from bot.db.session import create_engine, create_session_factory
from bot.handlers import get_root_router
from bot.middlewares.db import DbSessionMiddleware, UserMiddleware
from bot.utils.logs import setup_logging

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="list", description="Мои дедлайны"),
    BotCommand(command="add", description="Добавить дедлайн"),
    BotCommand(command="edit", description="Изменить свой дедлайн"),
    BotCommand(command="delete", description="Удалить свой дедлайн"),
    BotCommand(command="subjects", description="Мои предметы"),
    BotCommand(command="help", description="Справка"),
]


def run_migrations(settings: Settings) -> None:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(Config("alembic.ini"), "head")


async def setup_bot_profile(bot: Bot) -> None:
    """Меню команд и описание бота. Аватарка ставится вручную через @BotFather."""
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_my_description(texts.BOT_DESCRIPTION)
    await bot.set_my_short_description(texts.BOT_SHORT_DESCRIPTION)


async def run_bot(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        await apply_seed(
            session, load_seed_file(settings.seed_path), sync_tracks=settings.seed_sync_tracks
        )

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Состояния диалогов хранятся в памяти: после перезапуска незаконченный диалог сбросится
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserMiddleware())
    dp.include_router(get_root_router())

    await setup_bot_profile(bot)
    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    run_migrations(settings)
    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
