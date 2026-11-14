"""/subjects и общие обработчики выбора предметов.

При онбординге отметки сразу пишутся в БД. В /subjects изменения копятся
в черновике (FSM) и применяются кнопкой «Сохранить»: одно сохранение с изменениями
тратит одну из попыток, доступных студенту (лимит в настройках).
"""

import logging
from collections.abc import Sequence

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import User
from bot.db.repositories import CatalogRepo, ChangeRequestRepo, SubscriptionRepo, UserRepo
from bot.handlers.screens import Screen, edit_screen, locked_screen, onboarding_screen
from bot.keyboards.subjects import (
    ChoiceAction,
    ChoiceCb,
    PickerAction,
    PickerMode,
    SubjectPickCb,
    choice_keyboard,
    picker_keyboard,
)
from bot.services.permissions import can_change_subjects, is_admin, subject_changes_left
from bot.services.subjects import (
    ChoiceState,
    SubjectsDraft,
    UserSubjects,
    apply_draft,
    load_user_subjects,
    with_draft,
)
from bot.utils.telegram import callback_message, edit_markup, edit_text

logger = logging.getLogger(__name__)
router = Router(name="subjects")

DRAFT_KEY = "subjects_draft"


async def _get_draft(state: FSMContext, subjects: UserSubjects) -> SubjectsDraft:
    raw = (await state.get_data()).get(DRAFT_KEY)
    return SubjectsDraft.from_dict(raw) if raw else SubjectsDraft.from_subjects(subjects)


async def _save_draft(state: FSMContext, draft: SubjectsDraft) -> None:
    await state.update_data({DRAFT_KEY: draft.to_dict()})


async def _clear_draft(state: FSMContext) -> None:
    await state.update_data({DRAFT_KEY: None})


async def subjects_screen(
    session: AsyncSession, user: User, subjects: UserSubjects, draft: SubjectsDraft | None = None
) -> Screen:
    """Что показать в /subjects: незакрытый обязательный выбор, редактор или блокировку."""
    assert user.track is not None
    if not subjects.unresolved_choices and not can_change_subjects(user):
        pending = await ChangeRequestRepo(session).get_open_for_user(user.id)
        return locked_screen(user.track.name, subjects, request_pending=pending is not None)
    view = with_draft(subjects, draft) if draft else subjects
    return edit_screen(user.track.name, view, subject_changes_left(user))


@router.message(Command("subjects"))
async def cmd_subjects(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.set_state(None)
    await _clear_draft(state)  # каждый /subjects — новый сеанс редактирования
    if not user.is_onboarded or user.track is None:
        await message.answer(texts.NEED_ONBOARDING)
        return

    subjects = await load_user_subjects(session, user)
    text, markup = await subjects_screen(session, user, subjects)
    await message.answer(text, reply_markup=markup)


@router.callback_query(ChoiceCb.filter())
async def on_choice(
    callback: CallbackQuery,
    callback_data: ChoiceCb,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    """Группа «выбери один» (например, Python или Java)."""
    message = callback_message(callback)
    if message is None or user.track is None:
        await callback.answer()
        return

    subjects = await load_user_subjects(session, user)
    mode = callback_data.mode
    draft = await _get_draft(state, subjects) if mode == PickerMode.EDIT else None

    if callback_data.action == ChoiceAction.OPEN:
        choice = with_draft(subjects, draft).choice(callback_data.group_id) if draft else None
        if choice is None:
            await callback.answer("Этот выбор больше недоступен", show_alert=True)
            return
        await edit_text(
            message, texts.CHOOSE_ONE_EDIT, choice_keyboard(choice, mode, show_back=True)
        )
        await callback.answer()
        return

    if callback_data.action == ChoiceAction.PICK:
        saved = subjects.choice(callback_data.group_id)
        if saved is None or callback_data.subject_id not in {s.id for s in saved.options}:
            await callback.answer("Этот вариант больше недоступен", show_alert=True)
            return

        if mode == PickerMode.ONBOARDING or saved.chosen is None:
            # Онбординг или обязательный выбор, которого ещё нет, — сохраняем сразу и бесплатно
            group = await CatalogRepo(session).get_choice_group(saved.group_id)
            assert group is not None
            await SubscriptionRepo(session).choose_option(user.id, group, callback_data.subject_id)
            logger.info(
                "User %s picked subject %s in group %s", user.id, callback_data.subject_id, group.id
            )
            subjects = await load_user_subjects(session, user)
        elif draft is not None:
            if not can_change_subjects(user):
                await callback.answer(texts.SUBJECTS_LIMIT_REACHED, show_alert=True)
                return
            draft.choices[saved.group_id] = callback_data.subject_id
            await _save_draft(state, draft)

    if mode == PickerMode.ONBOARDING and not user.is_onboarded:
        screen = onboarding_screen(user.track.name, subjects)
    else:
        screen = await subjects_screen(session, user, subjects, draft)
    await edit_text(message, *screen)
    await callback.answer()


@router.callback_query(SubjectPickCb.filter())
async def on_subject_picker(
    callback: CallbackQuery,
    callback_data: SubjectPickCb,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    """Предметы по выбору: разделы, отметки ✅, страницы, «Готово» / «Сохранить» / «Отмена»."""
    message = callback_message(callback)
    if message is None or user.track is None or callback_data.action == PickerAction.NOOP:
        await callback.answer()
        return

    subjects = await load_user_subjects(session, user)
    if callback_data.mode == PickerMode.ONBOARDING and not user.is_onboarded:
        await _onboarding_picker(callback, callback_data, message, session, user, subjects)
    else:
        await _edit_picker(callback, callback_data, message, session, user, subjects, state)


async def _onboarding_picker(
    callback: CallbackQuery,
    callback_data: SubjectPickCb,
    message: Message,
    session: AsyncSession,
    user: User,
    subjects: UserSubjects,
) -> None:
    assert user.track is not None
    action = callback_data.action
    selected = set(subjects.selected_elective_ids)

    if action == PickerAction.DONE:
        if subjects.unresolved_choices:
            await edit_text(message, *onboarding_screen(user.track.name, subjects))
            await callback.answer("Сначала выбери обязательный предмет")
            return
        await UserRepo(session).mark_onboarded(user)
        logger.info("User %s finished onboarding with %d electives", user.id, len(selected))
        await edit_text(
            message, texts.onboarding_done(subjects.mandatory, subjects.selected_groups())
        )
        await callback.answer()
        return

    if action == PickerAction.TOGGLE:
        subject_id = callback_data.subject_id
        if subject_id not in {s.id for s in subjects.electives}:
            await callback.answer("Этот предмет нельзя выбрать", show_alert=True)
            return
        repo = SubscriptionRepo(session)
        if subject_id in selected:
            await repo.unsubscribe(user.id, {subject_id})
            selected.discard(subject_id)
        else:
            await repo.subscribe(user.id, {subject_id})
            selected.add(subject_id)

    await edit_markup(message, _picker_after(callback_data, subjects, selected, choices=()))
    await callback.answer()


async def _edit_picker(
    callback: CallbackQuery,
    callback_data: SubjectPickCb,
    message: Message,
    session: AsyncSession,
    user: User,
    subjects: UserSubjects,
    state: FSMContext,
) -> None:
    action = callback_data.action

    if action == PickerAction.CANCEL:
        await _clear_draft(state)
        await edit_text(message, texts.SUBJECTS_CHANGES_CANCELLED)
        await callback.answer()
        return

    if not can_change_subjects(user):
        await callback.answer(texts.SUBJECTS_LIMIT_REACHED, show_alert=True)
        return

    draft = await _get_draft(state, subjects)

    if action == PickerAction.DONE:
        if subjects.unresolved_choices:
            await edit_text(message, *await subjects_screen(session, user, subjects, draft))
            await callback.answer("Сначала выбери обязательный предмет")
            return
        changed = await apply_draft(session, user, subjects, draft)
        await _clear_draft(state)
        subjects = await load_user_subjects(session, user)
        if changed:
            if not is_admin(user.id):
                await UserRepo(session).count_subject_change(user)
            logger.info("User %s changed subjects (%d used)", user.id, user.subject_changes_used)
            text = texts.subjects_saved(
                subjects.mandatory, subjects.selected_groups(), subject_changes_left(user)
            )
        else:
            text = texts.subjects_unchanged(subjects.mandatory, subjects.selected_groups())
        await edit_text(message, text)
        await callback.answer()
        return

    if action == PickerAction.TOGGLE:
        subject_id = callback_data.subject_id
        if subject_id not in {s.id for s in subjects.electives}:
            await callback.answer("Этот предмет нельзя выбрать", show_alert=True)
            return
        draft.electives ^= {subject_id}
        await _save_draft(state, draft)

    view = with_draft(subjects, draft)
    markup = _picker_after(callback_data, view, view.selected_elective_ids, choices=view.choices)
    await edit_markup(message, markup)
    await callback.answer()


def _picker_after(
    callback_data: SubjectPickCb,
    subjects: UserSubjects,
    selected: set[int],
    choices: Sequence[ChoiceState],
) -> InlineKeyboardMarkup:
    """Клавиатура после действия: меню разделов (после «назад») или предметы раздела."""
    action = callback_data.action
    cat = None if action == PickerAction.BACK else callback_data.cat
    page = 0 if action == PickerAction.CATEGORY else callback_data.page
    return picker_keyboard(
        subjects.elective_groups, selected, callback_data.mode, cat=cat, page=page, choices=choices
    )
