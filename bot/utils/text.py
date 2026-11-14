"""Мелкие текстовые хелперы."""


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(1, ("день", "дня", "дней")) → "день"; 2 → "дня"; 5 → "дней"."""
    n = abs(n) % 100
    if 11 <= n <= 19:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
