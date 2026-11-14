"""Клавиатуры добавления, просмотра, изменения и удаления дедлайнов."""

from collections.abc import Sequence
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Deadline, Subject
from bot.utils.text import shorten
from bot.utils.time import format_due_short

DEADLINES_PER_PAGE = 8
BUTTON_TEXT_LIMIT = 60


# --- /add ---


class AddAction(StrEnum):
    SUBJECT = "s"
    SKIP_COMMENT = "k"
    SHARED = "a"  # для всех подписчиков предмета
    PERSONAL = "p"  # только для себя
    SAVE = "v"
    DUPLICATE_SAME = "ds"  # «Это он, не добавлять»
    DUPLICATE_OTHER = "do"  # «Это другой, добавить»
    CANCEL = "x"


class AddCb(CallbackData, prefix="add"):
    action: AddAction
    value: int = 0


def _cancel_row(kb: InlineKeyboardBuilder) -> None:
    row = InlineKeyboardBuilder()
    row.button(text="Отмена", callback_data=AddCb(action=AddAction.CANCEL))
    kb.attach(row)


def add_subject_keyboard(subjects: Sequence[Subject]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.button(
            text=shorten(subject.name, BUTTON_TEXT_LIMIT),
            callback_data=AddCb(action=AddAction.SUBJECT, value=subject.id),
        )
    kb.adjust(1)
    _cancel_row(kb)
    return kb.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _cancel_row(kb)
    return kb.as_markup()


def skip_comment_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Без комментария →", callback_data=AddCb(action=AddAction.SKIP_COMMENT))
    _cancel_row(kb)
    return kb.as_markup()


def visibility_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Для всех подписчиков", callback_data=AddCb(action=AddAction.SHARED))
    kb.button(text="🔒 Только для меня", callback_data=AddCb(action=AddAction.PERSONAL))
    kb.adjust(1)
    _cancel_row(kb)
    return kb.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сохранить", callback_data=AddCb(action=AddAction.SAVE))
    kb.button(text="Отмена", callback_data=AddCb(action=AddAction.CANCEL))
    kb.adjust(2)
    return kb.as_markup()


def duplicate_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Это он, не добавлять", callback_data=AddCb(action=AddAction.DUPLICATE_SAME))
    kb.button(text="Это другой, добавить", callback_data=AddCb(action=AddAction.DUPLICATE_OTHER))
    kb.adjust(1)
    return kb.as_markup()


# --- /list ---


class ListCb(CallbackData, prefix="list"):
    show_done: bool


def list_keyboard(done_count: int, show_done: bool) -> InlineKeyboardMarkup | None:
    if not done_count:
        return None
    kb = InlineKeyboardBuilder()
    if show_done:
        kb.button(text="Скрыть сданные", callback_data=ListCb(show_done=False))
    else:
        kb.button(text=f"Показать сданные ({done_count})", callback_data=ListCb(show_done=True))
    return kb.as_markup()


# --- /edit и /delete ---


class ManagePurpose(StrEnum):
    EDIT = "e"
    DELETE = "d"


class PickDeadlineCb(CallbackData, prefix="dpick"):
    purpose: ManagePurpose
    deadline_id: int = 0  # 0 — переключение страницы
    page: int = 0


def deadline_button_text(deadline: Deadline) -> str:
    lock = "🔒 " if deadline.is_personal else ""
    text = f"{format_due_short(deadline.due_at)} · {lock}{deadline.subject.name} — {deadline.title}"
    return shorten(text, BUTTON_TEXT_LIMIT)


def pick_deadline_keyboard(
    deadlines: Sequence[Deadline], purpose: ManagePurpose, page: int = 0
) -> InlineKeyboardMarkup:
    pages = max(1, (len(deadlines) + DEADLINES_PER_PAGE - 1) // DEADLINES_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    chunk = deadlines[page * DEADLINES_PER_PAGE : (page + 1) * DEADLINES_PER_PAGE]

    kb = InlineKeyboardBuilder()
    for deadline in chunk:
        kb.button(
            text=deadline_button_text(deadline),
            callback_data=PickDeadlineCb(purpose=purpose, deadline_id=deadline.id, page=page),
        )
    kb.adjust(1)
    if pages > 1:
        nav = InlineKeyboardBuilder()
        if page > 0:
            nav.button(text="◀️", callback_data=PickDeadlineCb(purpose=purpose, page=page - 1))
        if page < pages - 1:
            nav.button(text="▶️", callback_data=PickDeadlineCb(purpose=purpose, page=page + 1))
        kb.attach(nav)
    return kb.as_markup()


class EditField(StrEnum):
    TITLE = "t"
    DUE = "d"
    COMMENT = "c"
    SUBJECT = "s"
    CANCEL = "x"


class EditFieldCb(CallbackData, prefix="dedit"):
    deadline_id: int
    field: EditField


class EditSubjectCb(CallbackData, prefix="desub"):
    deadline_id: int
    subject_id: int


def edit_fields_keyboard(deadline_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for field, label in (
        (EditField.TITLE, "Название"),
        (EditField.DUE, "Дата и время"),
        (EditField.COMMENT, "Комментарий"),
        (EditField.SUBJECT, "Предмет"),
    ):
        kb.button(text=label, callback_data=EditFieldCb(deadline_id=deadline_id, field=field))
    kb.button(
        text="Отмена", callback_data=EditFieldCb(deadline_id=deadline_id, field=EditField.CANCEL)
    )
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def edit_subject_keyboard(deadline_id: int, subjects: Sequence[Subject]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for subject in subjects:
        kb.button(
            text=shorten(subject.name, BUTTON_TEXT_LIMIT),
            callback_data=EditSubjectCb(deadline_id=deadline_id, subject_id=subject.id),
        )
    kb.button(
        text="Отмена", callback_data=EditFieldCb(deadline_id=deadline_id, field=EditField.CANCEL)
    )
    kb.adjust(1)
    return kb.as_markup()


class DeleteCb(CallbackData, prefix="ddel"):
    deadline_id: int
    confirm: bool


def delete_confirm_keyboard(deadline_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Удалить", callback_data=DeleteCb(deadline_id=deadline_id, confirm=True))
    kb.button(text="Отмена", callback_data=DeleteCb(deadline_id=deadline_id, confirm=False))
    kb.adjust(2)
    return kb.as_markup()
