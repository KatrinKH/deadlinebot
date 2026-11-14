"""/add — пошаговое добавление дедлайна.

Предмет → название → срок → комментарий → «для всех» / «только для меня» → подтверждение.
Перед сохранением общего дедлайна ищем похожий, чтобы не плодить дубли.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.text_decorations import html_decoration as hd
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import Deadline, User
from bot.db.repositories import CatalogRepo, DeadlineRepo
from bot.keyboards.deadlines import (
    AddAction,
    AddCb,
    add_subject_keyboard,
    cancel_keyboard,
    confirm_keyboard,
    duplicate_keyboard,
    skip_comment_keyboard,
    visibility_keyboard,
)
from bot.services.deadlines import (
    DeadlineDraft,
    FieldError,
    check_not_past,
    clean_comment,
    clean_title,
)
from bot.services.duplicates import find_duplicates
from bot.services.subjects import load_user_subjects
from bot.utils.telegram import callback_message, edit_text
from bot.utils.time import DateParseError, now_local, parse_due

logger = logging.getLogger(__name__)
router = Router(name="add")

DRAFT_KEY = "deadline_draft"
TEXT_INPUT = F.text & ~F.text.startswith("/")


class AddDeadline(StatesGroup):
    subject = State()
    title = State()
    due = State()
    comment = State()
    visibility = State()
    confirm = State()
    duplicate = State()


async def get_draft(state: FSMContext) -> DeadlineDraft:
    return DeadlineDraft.from_dict((await state.get_data()).get(DRAFT_KEY) or {})


async def set_draft(state: FSMContext, draft: DeadlineDraft) -> None:
    await state.update_data({DRAFT_KEY: draft.to_dict()})


async def draft_card(session: AsyncSession, draft: DeadlineDraft) -> str:
    assert draft.subject_id is not None and draft.title and draft.due_at
    subject = await CatalogRepo(session).get_subject(draft.subject_id)
    return texts.deadline_card(
        subject.name if subject else "—",
        draft.title,
        draft.due_at,
        draft.comment,
        draft.is_personal,
    )


async def save_draft(session: AsyncSession, user: User, draft: DeadlineDraft) -> Deadline:
    """Сохраняет подтверждённый черновик. Общий для /add и добавления из текста."""
    assert draft.is_complete and draft.subject_id and draft.title and draft.due_at
    deadline = await DeadlineRepo(session).create(
        subject_id=draft.subject_id,
        title=draft.title,
        due_at=draft.due_at,
        author_id=user.id,
        comment=draft.comment or None,
        is_personal=bool(draft.is_personal),
        source=draft.source,
        was_corrected=draft.was_corrected,
    )
    logger.info(
        "User %s added deadline %s (personal=%s, source=%s)",
        user.id, deadline.id, deadline.is_personal, deadline.source.value,
    )  # fmt: skip
    return deadline


# --- Шаги диалога ---


@router.message(Command("add"))
async def cmd_add(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    if not user.is_onboarded:
        await message.answer(texts.NEED_ONBOARDING)
        return
    subjects = (await load_user_subjects(session, user)).subscribed
    if not subjects:
        await message.answer(texts.ADD_NO_SUBJECTS)
        return
    await state.set_state(AddDeadline.subject)
    await set_draft(state, DeadlineDraft())
    await message.answer(texts.ADD_CHOOSE_SUBJECT, reply_markup=add_subject_keyboard(subjects))


@router.callback_query(AddDeadline.subject, AddCb.filter(F.action == AddAction.SUBJECT))
async def on_subject(
    callback: CallbackQuery,
    callback_data: AddCb,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    subjects = {s.id: s for s in (await load_user_subjects(session, user)).subscribed}
    subject = subjects.get(callback_data.value)
    if subject is None:
        await callback.answer("Этого предмета нет в твоём списке", show_alert=True)
        return
    draft = await get_draft(state)
    draft.subject_id = subject.id
    await set_draft(state, draft)
    await state.set_state(AddDeadline.title)
    if message := callback_message(callback):
        text = f"Предмет: <b>{hd.quote(subject.name)}</b>\n\n{texts.ADD_ASK_TITLE}"
        await edit_text(message, text, cancel_keyboard())
    await callback.answer()


@router.message(AddDeadline.title, TEXT_INPUT)
async def on_title(message: Message, state: FSMContext) -> None:
    try:
        title = clean_title(message.text)
    except FieldError as e:
        await message.answer(texts.input_error(str(e)), reply_markup=cancel_keyboard())
        return
    draft = await get_draft(state)
    draft.title = title
    await set_draft(state, draft)
    await state.set_state(AddDeadline.due)
    await message.answer(texts.ADD_ASK_DUE, reply_markup=cancel_keyboard())


@router.message(AddDeadline.due, TEXT_INPUT)
async def on_due(message: Message, state: FSMContext) -> None:
    now = now_local()
    try:
        due_at = parse_due(message.text, now)
        check_not_past(due_at, now)
    except DateParseError as e:
        await message.answer(
            texts.input_error(str(e), texts.DUE_FORMAT_HELP), reply_markup=cancel_keyboard()
        )
        return
    except FieldError as e:
        await message.answer(texts.input_error(str(e)), reply_markup=cancel_keyboard())
        return
    draft = await get_draft(state)
    draft.due_at = due_at
    await set_draft(state, draft)
    await state.set_state(AddDeadline.comment)
    await message.answer(texts.ADD_ASK_COMMENT, reply_markup=skip_comment_keyboard())


@router.message(AddDeadline.comment, TEXT_INPUT)
async def on_comment(message: Message, state: FSMContext) -> None:
    try:
        comment = clean_comment(message.text)
    except FieldError as e:
        await message.answer(texts.input_error(str(e)), reply_markup=skip_comment_keyboard())
        return
    draft = await get_draft(state)
    draft.comment = comment or None
    await set_draft(state, draft)
    await state.set_state(AddDeadline.visibility)
    await message.answer(texts.ADD_ASK_VISIBILITY, reply_markup=visibility_keyboard())


@router.callback_query(AddDeadline.comment, AddCb.filter(F.action == AddAction.SKIP_COMMENT))
async def on_skip_comment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddDeadline.visibility)
    if message := callback_message(callback):
        await edit_text(message, texts.ADD_ASK_VISIBILITY, visibility_keyboard())
    await callback.answer()


@router.callback_query(
    AddDeadline.visibility, AddCb.filter(F.action.in_({AddAction.SHARED, AddAction.PERSONAL}))
)
async def on_visibility(
    callback: CallbackQuery, callback_data: AddCb, session: AsyncSession, state: FSMContext
) -> None:
    draft = await get_draft(state)
    draft.is_personal = callback_data.action == AddAction.PERSONAL
    await set_draft(state, draft)
    await state.set_state(AddDeadline.confirm)
    if message := callback_message(callback):
        card = await draft_card(session, draft)
        await edit_text(message, f"{texts.ADD_CONFIRM}\n\n{card}", confirm_keyboard())
    await callback.answer()


@router.callback_query(AddDeadline.confirm, AddCb.filter(F.action == AddAction.SAVE))
async def on_save(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    draft = await get_draft(state)
    message = callback_message(callback)
    try:
        check_not_past(draft.due_at, now_local())
    except FieldError as e:
        await state.set_state(AddDeadline.due)
        if message:
            await message.answer(
                texts.input_error(str(e), texts.ADD_ASK_DUE), reply_markup=cancel_keyboard()
            )
        await callback.answer()
        return

    if not draft.is_personal:
        candidates = await DeadlineRepo(session).list_duplicate_candidates(
            draft.subject_id, draft.due_at
        )
        duplicates = find_duplicates(candidates, draft.subject_id, draft.due_at, draft.title)
        if duplicates:
            await state.set_state(AddDeadline.duplicate)
            if message:
                await edit_text(message, texts.duplicate_found(duplicates[0]), duplicate_keyboard())
            await callback.answer()
            return

    await _finish(callback, session, user, state, draft)


@router.callback_query(AddDeadline.duplicate, AddCb.filter(F.action == AddAction.DUPLICATE_OTHER))
async def on_duplicate_other(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await _finish(callback, session, user, state, await get_draft(state))


@router.callback_query(AddDeadline.duplicate, AddCb.filter(F.action == AddAction.DUPLICATE_SAME))
async def on_duplicate_same(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    logger.info("User %s skipped a duplicate deadline", user.id)
    if message := callback_message(callback):
        await edit_text(message, texts.ADD_DUPLICATE_SKIPPED)
    await callback.answer()


async def _finish(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    draft: DeadlineDraft,
) -> None:
    deadline = await save_draft(session, user, draft)
    await state.clear()
    if message := callback_message(callback):
        card = texts.deadline_card(
            deadline.subject.name,
            deadline.title,
            deadline.due_at,
            deadline.comment,
            deadline.is_personal,
        )
        await edit_text(message, f"{card}\n\n{texts.add_saved(deadline.is_personal)}")
    await callback.answer("Сохранено")


# --- Отмена, неожиданный ввод, устаревшие кнопки ---


@router.callback_query(AddCb.filter(F.action == AddAction.CANCEL))
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Отмена» — общая для /add и ввода нового значения в /edit."""
    current = await state.get_state() or ""
    await state.clear()
    if message := callback_message(callback):
        is_edit = current.startswith("EditDeadline")
        await edit_text(message, texts.EDIT_CANCELLED if is_edit else texts.ADD_CANCELLED)
    await callback.answer()


@router.message(
    StateFilter(
        AddDeadline.subject, AddDeadline.visibility, AddDeadline.confirm, AddDeadline.duplicate
    ),
    ~F.text.startswith("/"),
)
async def on_text_instead_of_button(message: Message) -> None:
    await message.answer("Выбери вариант кнопкой выше — или /cancel, чтобы отменить.")


@router.message(
    StateFilter(AddDeadline.title, AddDeadline.due, AddDeadline.comment), ~F.text.startswith("/")
)
async def on_not_text(message: Message) -> None:
    await message.answer(texts.ADD_NEED_TEXT)


@router.callback_query(AddCb.filter())
async def on_stale(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_DIALOG, show_alert=True)
