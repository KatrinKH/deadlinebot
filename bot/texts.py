"""Тексты сообщений бота и хелперы форматирования."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from aiogram.utils.text_decorations import html_decoration as hd

from bot.db.models import Deadline, Subject
from bot.services.subjects import SubjectGroup
from bot.utils.text import plural
from bot.utils.time import format_due, time_left

# Описание бота: видно в профиле и на пустом экране чата до нажатия «Start».
# Telegram ограничивает длину: description — 512 символов, short description — 120.
BOT_DESCRIPTION = (
    "Все дедлайны по твоим предметам — в одном месте 📚\n\n"
    "• Выбери трек и предметы — увидишь только свои сроки\n"
    "• Перешли текст задания из LMS или сообщение преподавателя — "
    "я сам найду предмет и дату\n"
    "• Напомню за 3 дня, за день и за 3 часа\n"
    "• Один добавил дедлайн — получили все, кто изучает предмет\n\n"
    "Бот для студентов Центрального университета."
)

BOT_SHORT_DESCRIPTION = (
    "Дедлайны по твоим предметам в одном месте: добавляй одной вставкой текста "
    "и получай напоминания вовремя."
)

WELCOME = (
    "Привет! Я <b>DeadlineBot</b> — собираю дедлайны по твоим предметам в одном месте "
    "и напоминаю о них заранее.\n\n"
    "Дедлайны добавляют сами студенты: один добавил — все, кто изучает предмет, "
    "получили. Сначала выбери свой трек:"
)

NO_TRACKS = "Треки ещё не настроены. Напиши, пожалуйста, администратору бота."

NEED_ONBOARDING = "Сначала давай познакомимся — нажми /start и выбери трек и предметы."

HOW_TO_ADD = (
    "Чтобы добавить дедлайн — просто перешли мне текст задания из LMS "
    "или сообщение преподавателя. Вручную — командой /add."
)

HELP = (
    "<b>Что я умею</b>\n\n"
    "/list — мои ближайшие дедлайны\n"
    "/add — добавить дедлайн\n"
    "/edit — изменить свой дедлайн\n"
    "/delete — удалить свой дедлайн\n"
    "/subjects — мои предметы\n"
    "/cancel — отменить текущее действие\n"
    "/help — эта справка\n\n" + HOW_TO_ADD
)

FALLBACK = (
    "Пока не понимаю такие сообщения. Добавление дедлайнов из текста скоро появится.\n"
    "Список команд — /help."
)


def changes_left_line(left: int | None) -> str:
    if left is None:
        return "Ты админ — изменять предметы можно без ограничений."
    if left == 0:
        return "Самостоятельные изменения закончились — дальше через администратора."
    return (
        f"Изменить предметы самостоятельно можно ещё {left} {plural(left, ('раз', 'раза', 'раз'))}."
    )


def bullet_list(subjects: Iterable[Subject]) -> str:
    lines = [f"• {hd.quote(s.name)}" for s in subjects]
    return "\n".join(lines) if lines else "—"


def welcome_back(name: str) -> str:
    return f"С возвращением, {hd.quote(name)}! 👋\n\n{HELP}"


def track_chosen(track_name: str, mandatory: Iterable[Subject]) -> str:
    return (
        f"Трек: <b>{hd.quote(track_name)}</b>\n\n"
        f"Обязательные предметы добавлены автоматически:\n{bullet_list(mandatory)}\n\n"
        "Теперь отметь предметы по выбору — факультативы, soft skills, интенсивы и другие, "
        "которые ты проходишь, — и нажми «Готово»."
    )


def choose_one_onboarding(
    track_name: str, mandatory: Iterable[Subject], step: int, total: int
) -> str:
    counter = f" ({step} из {total})" if total > 1 else ""
    return (
        f"Трек: <b>{hd.quote(track_name)}</b>\n\n"
        f"Обязательные предметы добавлены автоматически:\n{bullet_list(mandatory)}\n\n"
        f"Ещё обязательный предмет на выбор{counter}. Что из этого ты изучаешь?"
    )


CHOOSE_ONE_EDIT = "Обязательный предмет на выбор. Что из этого ты изучаешь?"


def track_changed(track_name: str, mandatory: Iterable[Subject]) -> str:
    return (
        f"Трек изменён на <b>{hd.quote(track_name)}</b>.\n\n"
        f"Обязательные предметы:\n{bullet_list(mandatory)}\n\n"
        "Предметы по выбору остались без изменений — поправить их можно в /subjects."
    )


def subjects_overview(track_name: str, mandatory: Iterable[Subject], left: int | None) -> str:
    return (
        f"<b>Мои предметы</b>\n\n"
        f"Трек: {hd.quote(track_name)}\n"
        f"Обязательные 🔒:\n{bullet_list(mandatory)}\n\n"
        "Предметы по выбору — открой раздел и отметь нужные. "
        "Изменения применятся, когда нажмёшь «Сохранить».\n"
        f"{changes_left_line(left)}"
    )


def subjects_locked(
    track_name: str,
    mandatory: Iterable[Subject],
    groups: Sequence[SubjectGroup],
    request_pending: bool,
) -> str:
    tail = (
        "Твой запрос на изменение уже у администратора — я напишу, когда он ответит."
        if request_pending
        else "Самостоятельные изменения закончились. Если нужно что-то поменять — "
        "отправь запрос администратору."
    )
    return (
        f"<b>Мои предметы</b>\n\nТрек: {hd.quote(track_name)}\n\n"
        f"{subjects_summary(mandatory, groups)}\n\n{tail}"
    )


def subjects_summary(mandatory: Iterable[Subject], groups: Sequence[SubjectGroup]) -> str:
    parts = [f"<b>Обязательные</b> 🔒:\n{bullet_list(mandatory)}"]
    if groups:
        parts += [f"<b>{hd.quote(g.name)}</b>:\n{bullet_list(g.subjects)}" for g in groups]
    else:
        parts.append("<b>По выбору</b>: —")
    return "\n\n".join(parts)


def onboarding_done(mandatory: Iterable[Subject], groups: Sequence[SubjectGroup]) -> str:
    return (
        "Готово! 🎉 Твои предметы:\n\n"
        f"{subjects_summary(mandatory, groups)}\n\n"
        f"{HOW_TO_ADD}\n\n"
        "Изменить предметы можно в любой момент: /subjects"
    )


def subjects_saved(
    mandatory: Iterable[Subject], groups: Sequence[SubjectGroup], left: int | None
) -> str:
    return f"Сохранено ✅\n\n{subjects_summary(mandatory, groups)}\n\n{changes_left_line(left)}"


def subjects_unchanged(mandatory: Iterable[Subject], groups: Sequence[SubjectGroup]) -> str:
    return (
        "Ничего не изменилось — попытка изменения не потрачена.\n\n"
        f"{subjects_summary(mandatory, groups)}"
    )


SUBJECTS_CHANGES_CANCELLED = "Изменения отменены. Посмотреть предметы — /subjects"
SUBJECTS_LIMIT_REACHED = (
    "Самостоятельные изменения закончились — открой /subjects и отправь запрос."
)
TRACK_CHANGE_LIMIT = "Сменить трек нельзя: самостоятельные изменения закончились. Открой /subjects."

# --- Запрос к админу на изменение предметов ---

ASK_CHANGE_REQUEST = (
    "Напиши одним сообщением, что нужно поменять. Например: "
    "«убрать Переговоры, добавить Публичные выступления» или «перейти на трек Обычный».\n\n"
    "Передумал(а) — /cancel"
)
CHANGE_REQUEST_EMPTY = "Напиши текстом, что нужно поменять, или /cancel."
CHANGE_REQUEST_SENT = "Запрос отправлен администратору. Я напишу, когда он ответит."
CHANGE_REQUEST_ALREADY_OPEN = "Запрос уже отправлен — ждём ответа администратора."
CHANGE_REQUEST_APPROVED = (
    "Администратор разрешил ещё одно изменение предметов ✅\nОткрой /subjects и поменяй, что нужно."
)
CHANGE_REQUEST_REJECTED = (
    "Администратор отклонил запрос на изменение предметов. Если что-то не так — напиши ему."
)
CANCELLED = "Отменено."


def change_request_for_admin(
    name: str,
    username: str | None,
    user_id: int,
    track_name: str,
    mandatory: Iterable[Subject],
    groups: Sequence[SubjectGroup],
    text: str,
) -> str:
    who = hd.quote(name) + (f" (@{hd.quote(username)})" if username else "")
    return (
        f"✉️ <b>Запрос на изменение предметов</b>\n\n"
        f"От: {hd.link(who, f'tg://user?id={user_id}')}\n"
        f"Трек: {hd.quote(track_name)}\n\n"
        f"<b>Просьба:</b>\n{hd.quote(text)}\n\n"
        f"<b>Сейчас:</b>\n{subjects_summary(mandatory, groups)}"
    )


def change_request_resolved(original: str, approved: bool) -> str:
    verdict = "✅ Разрешено одно изменение" if approved else "❌ Отклонено"
    return f"{original}\n\n<b>{verdict}</b>"


# --- Дедлайны: общие элементы ---

DUE_FORMAT_HELP = (
    "Напиши дату и время, например:\n"
    "• <code>25.11 18:00</code>\n"
    "• <code>25 ноября</code> — до 23:59\n"
    "• <code>завтра в 12:00</code>"
)


def deadline_card(
    subject_name: str,
    title: str,
    due_at: datetime,
    comment: str | None,
    is_personal: bool | None,
) -> str:
    lines = [
        f"<b>{hd.quote(subject_name)}</b>",
        f"📌 {hd.quote(title)}",
        f"📅 {format_due(due_at)} · {time_left(due_at)}",
    ]
    if comment:
        lines.append(f"💬 {hd.quote(comment)}")
    if is_personal is True:
        lines.append("🔒 Только для тебя")
    elif is_personal is False:
        lines.append("👥 Для всех, кто изучает предмет")
    return "\n".join(lines)


def deadline_line(deadline: Deadline, done: bool = False) -> str:
    """Дедлайн в списке /list."""
    mark = "✅ " if done else ""
    lock = " 🔒" if deadline.is_personal else ""
    lines = [
        f"{mark}📅 <b>{format_due(deadline.due_at)}</b> · {time_left(deadline.due_at)}",
        f"<b>{hd.quote(deadline.subject.name)}</b> — {hd.quote(deadline.title)}{lock}",
    ]
    if deadline.comment:
        lines.append(f"<i>{hd.quote(deadline.comment)}</i>")
    return "\n".join(lines)


STALE_DIALOG = "Этот диалог уже закрыт. Начни заново командой."
NO_ACCESS = "Этот дедлайн может изменить только автор или администратор."
DEADLINE_GONE = "Этот дедлайн уже удалён."

# --- /add ---

ADD_NO_SUBJECTS = "У тебя пока нет предметов. Выбери их в /subjects."
ADD_CHOOSE_SUBJECT = "<b>Новый дедлайн</b>\n\nПо какому предмету?"
ADD_ASK_TITLE = "Как называется задание? Например: «ДЗ 3» или «Эссе про переговоры»."
ADD_ASK_DUE = f"Когда срок сдачи?\n\n{DUE_FORMAT_HELP}"
ADD_ASK_COMMENT = (
    "Добавь комментарий, если нужно: что сдавать, куда, в каком формате. "
    "Или нажми «Без комментария»."
)
ADD_ASK_VISIBILITY = (
    "Кому показать дедлайн?\n\n"
    "👥 <b>Для всех</b> — увидят все, кто изучает предмет, и получат напоминания.\n"
    "🔒 <b>Только для меня</b> — личный дедлайн, его видишь только ты."
)
ADD_CONFIRM = "Проверь и сохрани:"
ADD_CANCELLED = "Добавление отменено."
ADD_DUPLICATE_SKIPPED = "Хорошо, не добавляю — этот дедлайн уже есть в списке у всех. /list"
ADD_NEED_TEXT = "Пришли, пожалуйста, текстом."


def add_saved(is_personal: bool) -> str:
    who = "Он виден только тебе." if is_personal else "Его увидят все, кто изучает этот предмет."
    return f"Дедлайн сохранён ✅ {who}\n\nВсе дедлайны — /list"


def duplicate_found(deadline: Deadline) -> str:
    card = deadline_card(
        deadline.subject.name, deadline.title, deadline.due_at, deadline.comment, None
    )
    return (
        f"Похоже, такой дедлайн уже есть:\n\n{card}"
        f"\n\nДобавил(а): {hd.quote(deadline.author.full_name)}"
    )


def input_error(error: str, hint: str = "") -> str:
    return f"⚠️ {hd.quote(error)}" + (f"\n\n{hint}" if hint else "")


# --- /list ---

LIST_EMPTY = (
    "Ближайших дедлайнов нет 🎉\n\n"
    "Знаешь срок, которого тут нет? Добавь его — /add, и он появится у всех, кто изучает предмет."
)
LIST_ALL_DONE = "Все ближайшие дедлайны сданы 🎉"
LIST_LIMIT = 30


def list_text(lines: Sequence[str], hidden_done: int, more: int) -> str:
    parts = ["<b>Мои дедлайны</b>", *lines]
    if more:
        parts.append(f"…и ещё {more}")
    if hidden_done:
        parts.append(f"<i>Сданных скрыто: {hidden_done}</i>")
    return "\n\n".join(parts)


# --- /edit и /delete ---

NOTHING_TO_EDIT = (
    "Тебе нечего изменять: ты ещё не добавлял(а) дедлайнов с будущим сроком.\n"
    "Нашёл(ла) ошибку в чужом дедлайне — нажми «Ошибка в дедлайне» под напоминанием."
)
NOTHING_TO_DELETE = "Тебе нечего удалять: ты ещё не добавлял(а) дедлайнов с будущим сроком."
EDIT_CHOOSE = "Какой дедлайн изменить?"
DELETE_CHOOSE = "Какой дедлайн удалить?"
EDIT_WHAT = "Что изменить?"
EDIT_ASK_TITLE = "Новое название:"
EDIT_ASK_DUE = f"Новый срок.\n\n{DUE_FORMAT_HELP}"
EDIT_ASK_COMMENT = "Новый комментарий (или «-», чтобы убрать):"
EDIT_ASK_SUBJECT = "Новый предмет:"
EDIT_CANCELLED = "Изменение отменено."
DELETE_CANCELLED = "Удаление отменено."


def edit_saved(card: str) -> str:
    return f"Сохранено ✅\n\n{card}"


def delete_confirm(card: str) -> str:
    return f"Удалить дедлайн?\n\n{card}"


def deleted(notified: int) -> str:
    tail = f" Уведомление получили подписчики предмета: {notified}." if notified else ""
    return f"Дедлайн удалён 🗑{tail}"


def deadline_changed_notice(card: str, editor_name: str) -> str:
    return f"✏️ <b>Дедлайн изменён</b> (изменил(а) {hd.quote(editor_name)})\n\n{card}"


def deadline_deleted_notice(card: str, editor_name: str) -> str:
    return f"🗑 <b>Дедлайн удалён</b> (удалил(а) {hd.quote(editor_name)})\n\n{card}"
