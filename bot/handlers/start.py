"""Онбординг: /start → выбор трека → выбор выборных предметов."""

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import User
from bot.db.repositories import CatalogRepo, SubscriptionRepo, UserRepo
from bot.handlers.screens import edit_screen, onboarding_screen
from bot.keyboards.subjects import TrackCb, tracks_keyboard
from bot.services.permissions import can_change_subjects, is_admin, subject_changes_left
from bot.services.subjects import load_user_subjects
from bot.utils.telegram import callback_message, edit_text

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, user: User) -> None:
    if user.is_onboarded:
        await message.answer(texts.welcome_back(user.full_name))
        return

    tracks = await CatalogRepo(session).list_tracks()
    if not tracks:
        await message.answer(texts.NO_TRACKS)
        return
    await message.answer(texts.WELCOME, reply_markup=tracks_keyboard(tracks))


@router.callback_query(TrackCb.filter(), F.message)
async def on_track_chosen(
    callback: CallbackQuery, callback_data: TrackCb, session: AsyncSession, user: User
) -> None:
    track = await CatalogRepo(session).get_track(callback_data.track_id)
    if track is None:
        await callback.answer("Такого трека больше нет", show_alert=True)
        return

    changing = user.is_onboarded and user.track_id != track.id
    if changing and not can_change_subjects(user):
        await callback.answer(texts.TRACK_CHANGE_LIMIT, show_alert=True)
        return

    # Обязательные предметы старого трека убираем, нового — добавляем
    await SubscriptionRepo(session).switch_track(user.id, user.track, track)
    users = UserRepo(session)
    await users.set_track(user, track.id)
    if changing and not is_admin(user.id):
        await users.count_subject_change(user)  # смена трека — тоже изменение предметов
    logger.info("User %s chose track %s", user.id, track.id)

    message = callback_message(callback)
    if message is not None:
        subjects = await load_user_subjects(session, user)
        if not user.is_onboarded:
            await edit_text(message, *onboarding_screen(track.name, subjects))
        elif subjects.unresolved_choices:
            await edit_text(message, *edit_screen(track.name, subjects, subject_changes_left(user)))
        else:
            await edit_text(message, texts.track_changed(track.name, subjects.mandatory))
    await callback.answer()
