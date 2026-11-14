"""Проверки прав. Собраны в одном месте, чтобы правила не расползались по хендлерам."""

from bot.config import get_settings
from bot.db.models import Deadline, User


def is_admin(user_id: int) -> bool:
    return user_id == get_settings().admin_id


def subject_changes_left(user: User) -> int | None:
    """Сколько раз студент ещё может сам изменить предметы. None — без ограничений (админ)."""
    if is_admin(user.id):
        return None
    allowed = get_settings().subject_change_limit + user.subject_changes_granted
    return max(0, allowed - user.subject_changes_used)


def can_change_subjects(user: User) -> bool:
    left = subject_changes_left(user)
    return left is None or left > 0


def can_manage_deadline(user_id: int, deadline: Deadline) -> bool:
    """Изменять и удалять дедлайн может автор; админ — любой общий (чужие личные не видит никто)."""
    if deadline.author_id == user_id:
        return True
    return is_admin(user_id) and not deadline.is_personal
