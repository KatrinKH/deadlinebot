"""Поиск похожих дедлайнов перед сохранением общего дедлайна.

Похожий = тот же предмет, срок в пределах суток, похожее название.
Сравнение названий — чистые функции, чтобы их было легко тестировать.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from bot.db.models import Deadline

DUE_WINDOW = timedelta(days=1)
SIMILARITY_THRESHOLD = 0.6

_NUMBER_RE = re.compile(r"\d+")


def normalize_title(title: str) -> str:
    title = title.lower().replace("ё", "е")
    title = re.sub(r"[^\w\s]", " ", title)
    return " ".join(title.split())


def title_similarity(a: str, b: str) -> float:
    """Похожесть названий от 0 до 1.

    «ДЗ 3» и «ДЗ 4» — разные задания, поэтому при разных номерах похожесть 0.
    """
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    numbers_a, numbers_b = set(_NUMBER_RE.findall(a)), set(_NUMBER_RE.findall(b))
    if numbers_a and numbers_b and numbers_a != numbers_b:
        return 0.0
    if a in b or b in a:
        return 0.9
    words_a, words_b = set(a.split()), set(b.split())
    jaccard = len(words_a & words_b) / len(words_a | words_b)
    return max(SequenceMatcher(None, a, b).ratio(), jaccard)


def is_due_close(a: datetime, b: datetime) -> bool:
    return abs(a - b) <= DUE_WINDOW


def find_duplicates(
    candidates: Sequence[Deadline], subject_id: int, due_at: datetime, title: str
) -> list[Deadline]:
    """Похожие общие дедлайны, самые похожие — первыми."""
    scored = [
        (title_similarity(d.title, title), d)
        for d in candidates
        if d.subject_id == subject_id
        and not d.is_personal
        and d.deleted_at is None
        and is_due_close(d.due_at, due_at)
    ]
    scored = [(score, d) for score, d in scored if score >= SIMILARITY_THRESHOLD]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [d for _, d in scored]
