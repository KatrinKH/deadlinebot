"""Работа с датами: разбор ввода студента, форматирование, «осталось N дней».

Все даты внутри бота — aware-datetime. В БД хранится UTC,
пользователь вводит и видит время в часовом поясе из настроек (Europe/Moscow).
"""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bot.config import get_settings
from bot.utils.text import plural

DEFAULT_TIME = time(23, 59)  # если время не указано — до конца дня

MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}  # fmt: skip
MONTH_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
RELATIVE_DAYS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}

_TIME_RE = re.compile(r"(?:^|\s)(?:в\s+)?(\d{1,2})[:.](\d{2})$")
_DOTTED_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_WORDS_RE = re.compile(r"^(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?$")


class DateParseError(ValueError):
    """Не получилось понять дату. Текст ошибки можно показать пользователю."""


def local_tz() -> ZoneInfo:
    return get_settings().tz


def now_local() -> datetime:
    return datetime.now(local_tz())


def parse_due(text: str, now: datetime | None = None) -> datetime:
    """Разбирает срок, введённый студентом.

    Понимает: «25.11», «25.11 18:00», «25.11.2026 18:00», «2026-11-25 18:00»,
    «25 ноября», «25 ноября 18:00», «завтра», «завтра в 18:00», «18:00» (сегодня).
    Без времени — 23:59. Без года — ближайшая такая дата (в декабре «10.01» — следующий год).
    Возвращает aware-datetime в часовом поясе `now` (по умолчанию — из настроек).
    """
    now = now or now_local()
    raw = " ".join(text.strip().lower().replace("ё", "е").split())
    raw = re.sub(r"^до\s+", "", raw)
    if not raw:
        raise DateParseError("Пустая дата")

    due_time = DEFAULT_TIME
    match = _TIME_RE.search(raw)
    # «25.11» без всего остального — это дата, а не время 25:11.
    # Время без даты понимаем только через двоеточие: «18:00».
    if match and not (match.start() == 0 and ":" not in match[0]):
        due_time = _make_time(int(match[1]), int(match[2]))
        raw = raw[: match.start()].strip()

    due_date = _parse_date(raw, now.date()) if raw else now.date()
    return datetime.combine(due_date, due_time, tzinfo=now.tzinfo)


def _make_time(hour: int, minute: int) -> time:
    try:
        return time(hour, minute)
    except ValueError:
        raise DateParseError(f"Такого времени не бывает: {hour}:{minute:02d}") from None


def _make_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise DateParseError(f"Такой даты не бывает: {day:02d}.{month:02d}.{year}") from None


def _with_nearest_year(month: int, day: int, today: date) -> date:
    candidate = _make_date(today.year, month, day)
    return candidate if candidate >= today else _make_date(today.year + 1, month, day)


def _parse_date(raw: str, today: date) -> date:
    if raw in RELATIVE_DAYS:
        return today + timedelta(days=RELATIVE_DAYS[raw])

    if match := _DOTTED_RE.match(raw):
        day, month, year = int(match[1]), int(match[2]), match[3]
        if year is None:
            return _with_nearest_year(month, day, today)
        return _make_date(int(year) + (2000 if len(year) == 2 else 0), month, day)

    if match := _ISO_RE.match(raw):
        return _make_date(int(match[1]), int(match[2]), int(match[3]))

    if match := _WORDS_RE.match(raw):
        month = next((num for prefix, num in MONTHS.items() if match[2].startswith(prefix)), None)
        if month is None:
            raise DateParseError(f"Не знаю такой месяц: {match[2]}")
        day = int(match[1])
        if match[3]:
            return _make_date(int(match[3]), month, day)
        return _with_nearest_year(month, day, today)

    raise DateParseError("Не получилось понять дату")


def format_due(due: datetime, now: datetime | None = None) -> str:
    """«пт, 21 ноября, 23:59» (год — только если не текущий)."""
    now = now or now_local()
    local = due.astimezone(now.tzinfo)
    year = f" {local.year}" if local.year != now.year else ""
    return (
        f"{WEEKDAYS[local.weekday()]}, {local.day} {MONTH_GENITIVE[local.month - 1]}{year}, "
        f"{local:%H:%M}"
    )


def format_due_short(due: datetime, now: datetime | None = None) -> str:
    """«21.11 23:59» — для кнопок."""
    now = now or now_local()
    return f"{due.astimezone(now.tzinfo):%d.%m %H:%M}"


def time_left(due: datetime, now: datetime | None = None) -> str:
    """«осталось 3 дня» / «осталось 5 часов» / «осталось 40 минут» / «срок прошёл»."""
    now = now or now_local()
    delta = due - now
    if delta.total_seconds() <= 0:
        return "срок прошёл"
    if delta >= timedelta(days=1):
        n = delta.days
        return f"осталось {n} {plural(n, ('день', 'дня', 'дней'))}"
    if delta >= timedelta(hours=1):
        n = int(delta.total_seconds() // 3600)
        return f"осталось {n} {plural(n, ('час', 'часа', 'часов'))}"
    n = max(1, int(delta.total_seconds() // 60))
    return f"осталось {n} {plural(n, ('минута', 'минуты', 'минут'))}"
