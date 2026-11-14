"""Черновик дедлайна и правила проверки полей.

Черновик собирается пошагово (/add) или из ответа LLM (этап 4)
и сохраняется только после подтверждения пользователем.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from bot.db.models import DeadlineSource

TITLE_MAX = 200
COMMENT_MAX = 500


class FieldError(ValueError):
    """Ошибка ввода. Текст показывается пользователю."""


@dataclass
class DeadlineDraft:
    subject_id: int | None = None
    title: str | None = None
    due_at: datetime | None = None
    comment: str | None = None
    is_personal: bool | None = None
    source: DeadlineSource = DeadlineSource.MANUAL
    was_corrected: bool = False  # пользователь правил поля, распознанные LLM

    @property
    def is_complete(self) -> bool:
        return (
            self.subject_id is not None
            and bool(self.title)
            and self.due_at is not None
            and self.is_personal is not None
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["due_at"] = self.due_at.isoformat() if self.due_at else None
        data["source"] = self.source.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeadlineDraft":
        data = dict(data)
        if data.get("due_at"):
            data["due_at"] = datetime.fromisoformat(data["due_at"])
        data["source"] = DeadlineSource(data.get("source", DeadlineSource.MANUAL.value))
        return cls(**data)


def clean_title(text: str) -> str:
    title = " ".join(text.split())
    if not title:
        raise FieldError("Название не может быть пустым.")
    if len(title) > TITLE_MAX:
        raise FieldError(f"Слишком длинное название — максимум {TITLE_MAX} символов.")
    return title


def clean_comment(text: str) -> str:
    comment = text.strip()
    if len(comment) > COMMENT_MAX:
        raise FieldError(f"Слишком длинный комментарий — максимум {COMMENT_MAX} символов.")
    return comment


def check_not_past(due_at: datetime, now: datetime) -> None:
    if due_at <= now:
        raise FieldError("Этот срок уже прошёл — нельзя добавить дедлайн в прошлом.")
