"""/list — мои дедлайны; /edit и /delete — для автора дедлайна и админа."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import Deadline, Subject, User
from bot.db.repositories import CatalogRepo, DeadlineRepo, SubscriptionRepo
from bot.keyboards.deadlines import (
    DeleteCb,
    EditField,
    EditFieldCb,
    EditSubjectCb,
    ListCb,
    ManagePurpose,
    PickDeadlineCb,
    cancel_keyboard,
    delete_confirm_keyboard,
    edit_fields_keyboard,
    edit_subject_keyboard,
    list_keyboard,
    pick_deadline_keyboard,
)
from bot.services.deadlines import FieldError, check_not_past, clean_comment, clean_title
from bot.services.notifications import broadcast
from bot.services.permissions import can_manage_deadline, is_admin
from bot.services.subjects import load_user_subjects
from bot.utils.telegram import callback_message, edit_markup, edit_text
from bot.utils.time import DateParseError, now_local, parse_due

logger = logging.getLogger(__name__)
router = Router(name="deadlines")


def card(deadline: Deadline) -> str:
    return texts.deadline_card(
        deadline.subject.name,
        deadline.title,
        deadline.due_at,
        deadline.comment,
        deadline.is_personal,
    )


# --- /list ---


async def build_list(session: AsyncSession, user: User, show_done: bool):
    subject_ids = await SubscriptionRepo(session).get_subject_ids(user.id)
    repo = DeadlineRepo(session)
    deadlines = await repo.list_visible(user.id, subject_ids, after=now_local())
    done_ids = await repo.completed_ids(user.id, {d.id for d in deadlines})

    if not deadlines:
        return texts.LIST_EMPTY, None
    shown = [d for d in deadlines if show_done or d.id not in done_ids]
    if not shown:
        return texts.LIST_ALL_DONE, list_keyboard(len(done_ids), show_done)

    lines = [texts.deadline_line(d, done=d.id in done_ids) for d in shown[: texts.LIST_LIMIT]]
    hidden_done = 0 if show_done else len(done_ids)
    text = texts.list_text(lines, hidden_done, more=max(0, len(shown) - texts.LIST_LIMIT))
    return text, list_keyboard(len(done_ids), show_done)


@router.message(Command("list"))
async def cmd_list(message: Message, session: AsyncSession, user: User) -> None:
    if not user.is_onboarded:
        await message.answer(texts.NEED_ONBOARDING)
        return
    text, markup = await build_list(session, user, show_done=False)
    await message.answer(text, reply_markup=markup)


@router.callback_query(ListCb.filter())
async def on_list_toggle(
    callback: CallbackQuery, callback_data: ListCb, session: AsyncSession, user: User
) -> None:
    if message := callback_message(callback):
        text, markup = await build_list(session, user, show_done=callback_data.show_done)
        await edit_text(message, text, markup)
    await callback.answer()


# --- выбор дедлайна для /edit и /delete ---


async def manageable(session: AsyncSession, user: User) -> list[Deadline]:
    deadlines = await DeadlineRepo(session).list_manageable(
        user.id, after=now_local(), admin=is_admin(user.id)
    )
    return list(deadlines)


@router.message(Command("edit"))
async def cmd_edit(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    deadlines = await manageable(session, user)
    if not deadlines:
        await message.answer(texts.NOTHING_TO_EDIT)
        return
    await message.answer(
        texts.EDIT_CHOOSE, reply_markup=pick_deadline_keyboard(deadlines, ManagePurpose.EDIT)
    )


@router.message(Command("delete"))
async def cmd_delete(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    deadlines = await manageable(session, user)
    if not deadlines:
        await message.answer(texts.NOTHING_TO_DELETE)
        return
    await message.answer(
        texts.DELETE_CHOOSE, reply_markup=pick_deadline_keyboard(deadlines, ManagePurpose.DELETE)
    )


async def load_manageable(
    callback: CallbackQuery, session: AsyncSession, user: User, deadline_id: int
) -> Deadline | None:
    """Дедлайн, если он существует и пользователь вправе им управлять; иначе — всплывашка."""
    deadline = await DeadlineRepo(session).get(deadline_id)
    if deadline is None:
        await callback.answer(texts.DEADLINE_GONE, show_alert=True)
        return None
    if not can_manage_deadline(user.id, deadline):
        await callback.answer(texts.NO_ACCESS, show_alert=True)
        return None
    return deadline


@router.callback_query(PickDeadlineCb.filter())
async def on_pick(
    callback: CallbackQuery, callback_data: PickDeadlineCb, session: AsyncSession, user: User
) -> None:
    message = callback_message(callback)
    if message is None:
        await callback.answer()
        return

    if callback_data.deadline_id == 0:  # переключение страницы
        deadlines = await manageable(session, user)
        await edit_markup(
            message, pick_deadline_keyboard(deadlines, callback_data.purpose, callback_data.page)
        )
        await callback.answer()
        return

    deadline = await load_manageable(callback, session, user, callback_data.deadline_id)
    if deadline is None:
        return
    if callback_data.purpose == ManagePurpose.EDIT:
        await edit_text(
            message, f"{card(deadline)}\n\n{texts.EDIT_WHAT}", edit_fields_keyboard(deadline.id)
        )
    else:
        await edit_text(
            message, texts.delete_confirm(card(deadline)), delete_confirm_keyboard(deadline.id)
        )
    await callback.answer()


# --- /edit ---


class EditDeadline(StatesGroup):
    value = State()


EDIT_PROMPTS = {
    EditField.TITLE: texts.EDIT_ASK_TITLE,
    EditField.DUE: texts.EDIT_ASK_DUE,
    EditField.COMMENT: texts.EDIT_ASK_COMMENT,
}


async def subjects_for_edit(session: AsyncSession, user: User, deadline: Deadline) -> list[Subject]:
    """Свои предметы; админу для чужого общего дедлайна — все предметы."""
    if is_admin(user.id) and deadline.author_id != user.id:
        return list(await CatalogRepo(session).list_subjects())
    return (await load_user_subjects(session, user)).subscribed


@router.callback_query(EditFieldCb.filter())
async def on_edit_field(
    callback: CallbackQuery,
    callback_data: EditFieldCb,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    message = callback_message(callback)
    if callback_data.field == EditField.CANCEL:
        await state.clear()
        if message:
            await edit_text(message, texts.EDIT_CANCELLED)
        await callback.answer()
        return

    deadline = await load_manageable(callback, session, user, callback_data.deadline_id)
    if deadline is None or message is None:
        return

    if callback_data.field == EditField.SUBJECT:
        subjects = await subjects_for_edit(session, user, deadline)
        await edit_text(
            message, texts.EDIT_ASK_SUBJECT, edit_subject_keyboard(deadline.id, subjects)
        )
    else:
        await state.set_state(EditDeadline.value)
        await state.update_data(edit_deadline_id=deadline.id, edit_field=callback_data.field.value)
        await message.answer(EDIT_PROMPTS[callback_data.field], reply_markup=cancel_keyboard())
    await callback.answer()


@router.callback_query(EditSubjectCb.filter())
async def on_edit_subject(
    callback: CallbackQuery,
    callback_data: EditSubjectCb,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    deadline = await load_manageable(callback, session, user, callback_data.deadline_id)
    if deadline is None:
        return
    allowed = {s.id for s in await subjects_for_edit(session, user, deadline)}
    if callback_data.subject_id not in allowed:
        await callback.answer("Этот предмет нельзя выбрать", show_alert=True)
        return

    old_subject_id = deadline.subject_id
    deadline.subject_id = callback_data.subject_id
    await session.flush()
    await session.refresh(deadline, ["subject"])
    await _after_edit(bot, session, user, deadline, old_subject_id)
    if message := callback_message(callback):
        await edit_text(message, texts.edit_saved(card(deadline)))
    await callback.answer()


@router.message(EditDeadline.value, F.text, ~F.text.startswith("/"))
async def on_edit_value(
    message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    field = EditField(data["edit_field"])
    deadline = await DeadlineRepo(session).get(data["edit_deadline_id"])
    if deadline is None or not can_manage_deadline(user.id, deadline):
        await state.clear()
        await message.answer(texts.DEADLINE_GONE if deadline is None else texts.NO_ACCESS)
        return

    try:
        if field == EditField.TITLE:
            deadline.title = clean_title(message.text)
        elif field == EditField.DUE:
            now = now_local()
            due_at = parse_due(message.text, now)
            check_not_past(due_at, now)
            deadline.due_at = due_at
        elif field == EditField.COMMENT:
            comment = clean_comment(message.text)
            deadline.comment = None if comment in {"", "-"} else comment
    except DateParseError as e:
        await message.answer(
            texts.input_error(str(e), texts.DUE_FORMAT_HELP), reply_markup=cancel_keyboard()
        )
        return
    except FieldError as e:
        await message.answer(texts.input_error(str(e)), reply_markup=cancel_keyboard())
        return

    await state.clear()
    await session.flush()
    await _after_edit(bot, session, user, deadline, deadline.subject_id)
    await message.answer(texts.edit_saved(card(deadline)))


async def _after_edit(
    bot: Bot, session: AsyncSession, editor: User, deadline: Deadline, old_subject_id: int
) -> None:
    logger.info("User %s edited deadline %s", editor.id, deadline.id)
    if deadline.is_personal:
        return
    repo = SubscriptionRepo(session)
    recipients = await repo.get_subscriber_ids(deadline.subject_id)
    if old_subject_id != deadline.subject_id:
        recipients |= await repo.get_subscriber_ids(old_subject_id)
    recipients.discard(editor.id)
    await broadcast(
        bot, recipients, texts.deadline_changed_notice(card(deadline), editor.full_name)
    )


# --- /delete ---


@router.callback_query(DeleteCb.filter())
async def on_delete(
    callback: CallbackQuery, callback_data: DeleteCb, session: AsyncSession, user: User, bot: Bot
) -> None:
    message = callback_message(callback)
    if not callback_data.confirm:
        if message:
            await edit_text(message, texts.DELETE_CANCELLED)
        await callback.answer()
        return

    deadline = await load_manageable(callback, session, user, callback_data.deadline_id)
    if deadline is None:
        return
    await DeadlineRepo(session).soft_delete(deadline)
    logger.info("User %s deleted deadline %s", user.id, deadline.id)

    notified = 0
    if not deadline.is_personal:
        recipients = await SubscriptionRepo(session).get_subscriber_ids(deadline.subject_id)
        recipients.discard(user.id)
        notice = texts.deadline_deleted_notice(card(deadline), user.full_name)
        notified = await broadcast(bot, recipients, notice)
    if message:
        await edit_text(message, texts.deleted(notified))
    await callback.answer()


@router.message(EditDeadline.value, ~F.text.startswith("/"))
async def on_edit_not_text(message: Message) -> None:
    await message.answer(texts.ADD_NEED_TEXT)
