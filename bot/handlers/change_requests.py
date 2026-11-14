"""Запрос к админу на изменение предметов, когда самостоятельные изменения закончились."""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import get_settings
from bot.db.models import ChangeRequestStatus, User
from bot.db.repositories import ChangeRequestRepo, UserRepo
from bot.keyboards.admin import ChangeDecision, ChangeDecisionCb, change_request_keyboard
from bot.keyboards.subjects import ChangeRequestCb
from bot.services.permissions import can_change_subjects, is_admin
from bot.services.subjects import load_user_subjects
from bot.utils.telegram import callback_message, edit_text

logger = logging.getLogger(__name__)
router = Router(name="change_requests")

MAX_REQUEST_LENGTH = 1000


class ChangeRequestForm(StatesGroup):
    text = State()


@router.callback_query(ChangeRequestCb.filter())
async def on_request_button(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if await ChangeRequestRepo(session).get_open_for_user(user.id):
        await callback.answer(texts.CHANGE_REQUEST_ALREADY_OPEN, show_alert=True)
        return
    if can_change_subjects(user):
        await callback.answer("Ты можешь изменить предметы сам — открой /subjects", show_alert=True)
        return
    await state.set_state(ChangeRequestForm.text)
    message = callback_message(callback)
    if message is not None:
        await message.answer(texts.ASK_CHANGE_REQUEST)
    await callback.answer()


@router.message(ChangeRequestForm.text, F.text, ~F.text.startswith("/"))
async def on_request_text(
    message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot
) -> None:
    await state.set_state(None)
    repo = ChangeRequestRepo(session)
    if await repo.get_open_for_user(user.id):
        await message.answer(texts.CHANGE_REQUEST_ALREADY_OPEN)
        return

    request = await repo.create(user.id, message.text[:MAX_REQUEST_LENGTH])
    logger.info("User %s created change request %s", user.id, request.id)

    subjects = await load_user_subjects(session, user)
    admin_text = texts.change_request_for_admin(
        name=user.full_name,
        username=user.username,
        user_id=user.id,
        track_name=user.track.name if user.track else "—",
        mandatory=subjects.mandatory,
        groups=subjects.selected_groups(),
        text=request.text,
    )
    try:
        await bot.send_message(
            get_settings().admin_id, admin_text, reply_markup=change_request_keyboard(request.id)
        )
    except TelegramAPIError:
        # Например, админ ещё ни разу не писал боту. Запрос сохранён в БД.
        logger.exception("Failed to notify admin about change request %s", request.id)
    await message.answer(texts.CHANGE_REQUEST_SENT)


@router.message(ChangeRequestForm.text, ~F.text.startswith("/"))
async def on_request_not_text(message: Message) -> None:
    await message.answer(texts.CHANGE_REQUEST_EMPTY)


@router.callback_query(ChangeDecisionCb.filter())
async def on_admin_decision(
    callback: CallbackQuery, callback_data: ChangeDecisionCb, session: AsyncSession, bot: Bot
) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return

    repo = ChangeRequestRepo(session)
    request = await repo.get(callback_data.request_id)
    if request is None or request.status != ChangeRequestStatus.OPEN:
        await callback.answer("Этот запрос уже обработан", show_alert=True)
        return

    approved = callback_data.decision == ChangeDecision.APPROVE
    await repo.resolve(
        request, ChangeRequestStatus.APPROVED if approved else ChangeRequestStatus.REJECTED
    )
    if approved:
        await UserRepo(session).grant_subject_change(request.user)
    logger.info("Change request %s %s", request.id, "approved" if approved else "rejected")

    try:
        await bot.send_message(
            request.user_id,
            texts.CHANGE_REQUEST_APPROVED if approved else texts.CHANGE_REQUEST_REJECTED,
        )
    except TelegramAPIError:
        logger.warning("Failed to notify user %s about request %s", request.user_id, request.id)

    message = callback_message(callback)
    if message is not None:
        await edit_text(message, texts.change_request_resolved(message.html_text, approved))
    await callback.answer("Готово")
