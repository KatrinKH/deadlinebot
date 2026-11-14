"""Клавиатуры выбора трека и предметов."""

from collections.abc import Sequence
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Subject, Track
from bot.services.subjects import ChoiceState, SubjectGroup

SUBJECTS_PER_PAGE = 8


class PickerMode(StrEnum):
    """Где открыт выбор: при первом запуске или из /subjects."""

    ONBOARDING = "onb"
    EDIT = "edit"


class PickerAction(StrEnum):
    CATEGORY = "c"  # открыть раздел
    BACK = "b"  # вернуться к списку разделов
    TOGGLE = "t"
    PAGE = "p"
    DONE = "d"  # «Готово» при онбординге / «Сохранить» в /subjects
    CANCEL = "x"  # отменить несохранённые изменения в /subjects
    NOOP = "n"


class TrackCb(CallbackData, prefix="track"):
    track_id: int


class SubjectPickCb(CallbackData, prefix="sp"):
    action: PickerAction
    mode: PickerMode
    cat: int = 0  # индекс раздела в списке разделов
    page: int = 0
    subject_id: int = 0


class ChoiceAction(StrEnum):
    OPEN = "o"  # открыть группу «выбери один», чтобы сменить выбор
    PICK = "p"
    BACK = "b"


class ChoiceCb(CallbackData, prefix="ch"):
    action: ChoiceAction
    mode: PickerMode
    group_id: int = 0
    subject_id: int = 0


def tracks_keyboard(tracks: Sequence[Track]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for track in tracks:
        kb.button(text=track.name, callback_data=TrackCb(track_id=track.id))
    kb.adjust(1)
    return kb.as_markup()


def page_count(total: int, per_page: int = SUBJECTS_PER_PAGE) -> int:
    return max(1, (total + per_page - 1) // per_page)


def clamp_page(page: int, total: int, per_page: int = SUBJECTS_PER_PAGE) -> int:
    return min(max(page, 0), page_count(total, per_page) - 1)


def _done_button(kb: InlineKeyboardBuilder, mode: PickerMode) -> None:
    done = InlineKeyboardBuilder()
    if mode == PickerMode.ONBOARDING:
        done.button(
            text="Готово ✔️", callback_data=SubjectPickCb(action=PickerAction.DONE, mode=mode)
        )
    else:
        done.button(
            text="Сохранить ✔️", callback_data=SubjectPickCb(action=PickerAction.DONE, mode=mode)
        )
        done.button(
            text="Отмена", callback_data=SubjectPickCb(action=PickerAction.CANCEL, mode=mode)
        )
        done.adjust(2)
    kb.attach(done)


def categories_keyboard(
    groups: Sequence[SubjectGroup], selected_ids: set[int], mode: PickerMode
) -> InlineKeyboardMarkup:
    """Список разделов с количеством выбранных предметов в каждом."""
    kb = InlineKeyboardBuilder()
    for index, group in enumerate(groups):
        chosen = sum(1 for s in group.subjects if s.id in selected_ids)
        suffix = f" · ✅ {chosen}" if chosen else ""
        kb.button(
            text=f"{group.name}{suffix}",
            callback_data=SubjectPickCb(action=PickerAction.CATEGORY, mode=mode, cat=index),
        )
    kb.adjust(1)
    _done_button(kb, mode)
    return kb.as_markup()


def electives_keyboard(
    subjects: Sequence[Subject],
    selected_ids: set[int],
    page: int,
    mode: PickerMode,
    cat: int = 0,
    show_back: bool = False,
) -> InlineKeyboardMarkup:
    """Предметы одного раздела с отметками ✅ и пагинацией."""
    page = clamp_page(page, len(subjects))
    start = page * SUBJECTS_PER_PAGE
    chunk = subjects[start : start + SUBJECTS_PER_PAGE]

    def cb(action: PickerAction, page: int = page, subject_id: int = 0) -> SubjectPickCb:
        return SubjectPickCb(action=action, mode=mode, cat=cat, page=page, subject_id=subject_id)

    kb = InlineKeyboardBuilder()
    for subject in chunk:
        mark = "✅ " if subject.id in selected_ids else "▫️ "
        kb.button(
            text=mark + subject.name, callback_data=cb(PickerAction.TOGGLE, subject_id=subject.id)
        )
    kb.adjust(1)

    pages = page_count(len(subjects))
    if pages > 1:
        nav = InlineKeyboardBuilder()
        if page > 0:
            nav.button(text="◀️", callback_data=cb(PickerAction.PAGE, page=page - 1))
        nav.button(text=f"{page + 1}/{pages}", callback_data=cb(PickerAction.NOOP))
        if page < pages - 1:
            nav.button(text="▶️", callback_data=cb(PickerAction.PAGE, page=page + 1))
        nav.adjust(3)
        kb.attach(nav)

    if show_back:
        back = InlineKeyboardBuilder()
        back.button(text="↩️ К разделам", callback_data=cb(PickerAction.BACK))
        kb.attach(back)

    _done_button(kb, mode)
    return kb.as_markup()


def choice_keyboard(
    choice: ChoiceState, mode: PickerMode, show_back: bool = False
) -> InlineKeyboardMarkup:
    """Варианты группы «выбери один»; текущий выбор отмечен ✅."""
    kb = InlineKeyboardBuilder()
    for subject in choice.options:
        mark = "✅ " if choice.chosen and choice.chosen.id == subject.id else ""
        kb.button(
            text=mark + subject.name,
            callback_data=ChoiceCb(
                action=ChoiceAction.PICK, mode=mode, group_id=choice.group_id, subject_id=subject.id
            ),
        )
    if show_back:
        kb.button(text="↩️ Назад", callback_data=ChoiceCb(action=ChoiceAction.BACK, mode=mode))
    kb.adjust(1)
    return kb.as_markup()


def picker_keyboard(
    groups: Sequence[SubjectGroup],
    selected_ids: set[int],
    mode: PickerMode,
    cat: int | None = None,
    page: int = 0,
    choices: Sequence[ChoiceState] = (),
) -> InlineKeyboardMarkup:
    """Выбор предметов по разделам.

    Если раздел один — сразу показываем его предметы. Иначе без `cat` —
    меню разделов, с `cat` — предметы выбранного раздела.
    `choices` — группы «выбери один»: над меню разделов появятся кнопки смены выбора.
    """
    markup = _picker_body(groups, selected_ids, mode, cat, page)
    if cat is None or len(groups) <= 1:
        rows = [
            [
                InlineKeyboardButton(
                    text=f"🔄 Сменить: {c.chosen.name}",
                    callback_data=ChoiceCb(
                        action=ChoiceAction.OPEN, mode=mode, group_id=c.group_id
                    ).pack(),
                )
            ]
            for c in choices
            if c.chosen is not None
        ]
        markup.inline_keyboard = rows + markup.inline_keyboard
    return markup


def _picker_body(
    groups: Sequence[SubjectGroup],
    selected_ids: set[int],
    mode: PickerMode,
    cat: int | None,
    page: int,
) -> InlineKeyboardMarkup:
    if not groups:
        kb = InlineKeyboardBuilder()
        _done_button(kb, mode)
        return kb.as_markup()
    if len(groups) == 1:
        return electives_keyboard(groups[0].subjects, selected_ids, page, mode)
    if cat is None or not 0 <= cat < len(groups):
        return categories_keyboard(groups, selected_ids, mode)
    return electives_keyboard(
        groups[cat].subjects, selected_ids, page, mode, cat=cat, show_back=True
    )


class ChangeRequestCb(CallbackData, prefix="creq"):
    """Кнопка «Запросить изменение» у студента, исчерпавшего лимит."""


def request_change_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Запросить изменение у администратора", callback_data=ChangeRequestCb())
    return kb.as_markup()
