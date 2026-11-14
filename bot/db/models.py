"""ORM-модели DeadlineBot.

Ключевая идея: дедлайны привязаны к предметам, а не к группам.
Студент подписывается на предметы (Subscription) и видит дедлайны только по ним.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base, UTCDateTime, utcnow


def _enum_column(enum_cls: type[enum.Enum], length: int) -> Enum:
    """Хранит enum строковым значением (manual/llm), без нативного типа БД — переносимо."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [m.value for m in members],
    )


DEFAULT_CATEGORY = "Другое"


class DeadlineSource(enum.StrEnum):
    MANUAL = "manual"
    LLM = "llm"


class ReportStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"  # дедлайн исправлен или удалён
    REJECTED = "rejected"  # жалоба отклонена


class ChangeRequestStatus(enum.StrEnum):
    OPEN = "open"
    APPROVED = "approved"  # админ разрешил ещё одно изменение
    REJECTED = "rejected"


class ReminderKind(enum.StrEnum):
    DAYS_3 = "3d"
    DAYS_1 = "1d"
    HOURS_3 = "3h"


# Обязательные предметы трека (many-to-many)
track_subjects = Table(
    "track_subjects",
    Base.metadata,
    Column("track_id", ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)

# Предметы, недоступные студентам трека (many-to-many)
track_hidden_subjects = Table(
    "track_hidden_subjects",
    Base.metadata,
    Column("track_id", ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)

# Варианты в группе «выбери один» (many-to-many)
choice_group_subjects = Table(
    "choice_group_subjects",
    Base.metadata,
    Column("group_id", ForeignKey("track_choice_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)

    # Предметы, обязательные для всех студентов трека
    mandatory_subjects: Mapped[list[Subject]] = relationship(
        secondary=track_subjects, lazy="selectin", order_by="Subject.name"
    )
    # Обязательные «на выбор»: например, Python или Java — студент выбирает один
    choice_groups: Mapped[list[TrackChoiceGroup]] = relationship(
        lazy="selectin",
        order_by="TrackChoiceGroup.position",
        cascade="all, delete-orphan",
    )
    # Недоступные студентам трека: не показываются в выборе (например, начнутся со 2 семестра)
    hidden_subjects: Mapped[list[Subject]] = relationship(
        secondary=track_hidden_subjects, lazy="selectin", order_by="Subject.name"
    )

    def fixed_ids(self) -> set[int]:
        return {s.id for s in self.mandatory_subjects}

    def subject_ids(self) -> set[int]:
        """Все предметы трека: обязательные и варианты из групп «выбери один»."""
        return self.fixed_ids().union(*({s.id for s in g.options} for g in self.choice_groups))

    def hidden_ids(self) -> set[int]:
        return {s.id for s in self.hidden_subjects}

    def __repr__(self) -> str:
        return f"Track(id={self.id}, name={self.name!r})"


class TrackChoiceGroup(Base):
    """Группа обязательных предметов трека, из которой студент выбирает ровно один."""

    __tablename__ = "track_choice_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    options: Mapped[list[Subject]] = relationship(
        secondary=choice_group_subjects, lazy="selectin", order_by="Subject.name"
    )

    def __repr__(self) -> str:
        return f"TrackChoiceGroup(id={self.id}, track_id={self.track_id})"


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    # Раздел в меню выбора: «Факультативы», «Soft skills», «Интенсивы» и т.п.
    category: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_CATEGORY, server_default=DEFAULT_CATEGORY
    )
    # Мягкое удаление: дедлайны и статистика по удалённому предмету не теряются
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    def __repr__(self) -> str:
        return f"Subject(id={self.id}, name={self.name!r})"


class User(Base):
    __tablename__ = "users"

    # Telegram ID как первичный ключ
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(64))
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"))

    # Настройки напоминаний
    remind_3d: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    remind_1d: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    remind_3h: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    # Онбординг завершён (выбраны трек и предметы)
    is_onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Сколько раз студент сам менял предметы после онбординга и сколько
    # дополнительных изменений разрешил админ (лимит задаётся в настройках)
    subject_changes_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    subject_changes_granted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    track: Mapped[Track | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.full_name!r})"


class Subscription(Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Deadline(Base):
    __tablename__ = "deadlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Личный дедлайн виден только автору
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    source: Mapped[DeadlineSource] = mapped_column(
        _enum_column(DeadlineSource, 16), default=DeadlineSource.MANUAL
    )
    # Пользователь исправлял поля, распознанные LLM (метрика качества распознавания)
    was_corrected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    # Мягкое удаление: сохраняем историю для статистики и жалоб
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    subject: Mapped[Subject] = relationship(lazy="selectin")
    author: Mapped[User] = relationship(lazy="selectin")


class Completion(Base):
    """Отметка «Сдал(а)»."""

    __tablename__ = "completions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    deadline_id: Mapped[int] = mapped_column(
        ForeignKey("deadlines.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Report(Base):
    """Жалоба на неверный дедлайн."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deadline_id: Mapped[int] = mapped_column(ForeignKey("deadlines.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReportStatus] = mapped_column(
        _enum_column(ReportStatus, 16), default=ReportStatus.OPEN, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    deadline: Mapped[Deadline] = relationship(lazy="selectin")
    reporter: Mapped[User] = relationship(lazy="selectin")


class ReminderLog(Base):
    """Отправленные напоминания. Уникальность защищает от повторной отправки."""

    __tablename__ = "reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "deadline_id", "kind", name="uq_reminder_logs_user_deadline_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    deadline_id: Mapped[int] = mapped_column(ForeignKey("deadlines.id", ondelete="CASCADE"))
    kind: Mapped[ReminderKind] = mapped_column(_enum_column(ReminderKind, 8))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChangeRequest(Base):
    """Запрос студента к админу на изменение предметов после исчерпания лимита."""

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[ChangeRequestStatus] = mapped_column(
        _enum_column(ChangeRequestStatus, 16), default=ChangeRequestStatus.OPEN, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(lazy="selectin")
