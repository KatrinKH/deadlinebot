"""Клавиатуры для администратора."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class ChangeDecision(StrEnum):
    APPROVE = "a"
    REJECT = "r"


class ChangeDecisionCb(CallbackData, prefix="cdec"):
    request_id: int
    decision: ChangeDecision


def change_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Разрешить одно изменение",
        callback_data=ChangeDecisionCb(request_id=request_id, decision=ChangeDecision.APPROVE),
    )
    kb.button(
        text="❌ Отклонить",
        callback_data=ChangeDecisionCb(request_id=request_id, decision=ChangeDecision.REJECT),
    )
    kb.adjust(1)
    return kb.as_markup()
