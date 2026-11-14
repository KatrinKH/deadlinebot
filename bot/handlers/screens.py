"""Экраны выбора предметов: какой текст и клавиатуру показать в текущем состоянии.

Общие для онбординга (/start) и редактирования (/subjects), поэтому вынесены отдельно.
"""

from aiogram.types import InlineKeyboardMarkup

from bot import texts
from bot.keyboards.subjects import (
    PickerMode,
    choice_keyboard,
    picker_keyboard,
    request_change_keyboard,
)
from bot.services.subjects import UserSubjects

Screen = tuple[str, InlineKeyboardMarkup | None]


def onboarding_screen(track_name: str, subjects: UserSubjects) -> Screen:
    """Сначала группы «выбери один» по очереди, потом предметы по выбору."""
    unresolved = subjects.unresolved_choices
    if unresolved:
        total = len(subjects.choices)
        step = total - len(unresolved) + 1
        return (
            texts.choose_one_onboarding(track_name, subjects.mandatory, step, total),
            choice_keyboard(unresolved[0], PickerMode.ONBOARDING),
        )
    return (
        texts.track_chosen(track_name, subjects.mandatory),
        picker_keyboard(
            subjects.elective_groups, subjects.selected_elective_ids, PickerMode.ONBOARDING
        ),
    )


def edit_screen(track_name: str, subjects: UserSubjects, changes_left: int | None) -> Screen:
    """Экран /subjects.

    `subjects` — с учётом несохранённого черновика. Если какой-то обязательный
    выбор «одно из» не сделан (например, трек обновился) — сначала спрашиваем его.
    """
    unresolved = subjects.unresolved_choices
    if unresolved:
        return texts.CHOOSE_ONE_EDIT, choice_keyboard(unresolved[0], PickerMode.EDIT)
    return (
        texts.subjects_overview(track_name, subjects.mandatory, changes_left),
        picker_keyboard(
            subjects.elective_groups,
            subjects.selected_elective_ids,
            PickerMode.EDIT,
            choices=subjects.choices,
        ),
    )


def locked_screen(track_name: str, subjects: UserSubjects, request_pending: bool) -> Screen:
    """Лимит самостоятельных изменений исчерпан: только просмотр и запрос админу."""
    text = texts.subjects_locked(
        track_name, subjects.mandatory, subjects.selected_groups(), request_pending
    )
    return text, None if request_pending else request_change_keyboard()
