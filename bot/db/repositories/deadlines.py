"""Дедлайны и отметки «Сдал(а)»."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.base import utcnow
from bot.db.models import Completion, Deadline, DeadlineSource, Subject
from bot.services.duplicates import DUE_WINDOW


class DeadlineRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        subject_id: int,
        title: str,
        due_at: datetime,
        author_id: int,
        comment: str | None = None,
        is_personal: bool = False,
        source: DeadlineSource = DeadlineSource.MANUAL,
        was_corrected: bool = False,
    ) -> Deadline:
        deadline = Deadline(
            subject_id=subject_id,
            title=title,
            due_at=due_at,
            author_id=author_id,
            comment=comment,
            is_personal=is_personal,
            source=source,
            was_corrected=was_corrected,
        )
        self.session.add(deadline)
        await self.session.flush()
        await self.session.refresh(deadline, ["subject", "author"])
        return deadline

    async def get(self, deadline_id: int) -> Deadline | None:
        """Дедлайн, если он не удалён."""
        deadline = await self.session.get(Deadline, deadline_id)
        return deadline if deadline is not None and deadline.deleted_at is None else None

    async def list_visible(
        self, user_id: int, subject_ids: set[int], after: datetime
    ) -> Sequence[Deadline]:
        """Дедлайны, которые видит пользователь, со сроком позже `after`.

        Общие — по предметам, на которые он подписан; личные — только свои.
        """
        result = await self.session.scalars(
            select(Deadline)
            .join(Subject, Subject.id == Deadline.subject_id)
            .where(
                Deadline.deleted_at.is_(None),
                Deadline.due_at > after,
                Subject.is_active.is_(True),
                or_(
                    and_(Deadline.is_personal.is_(False), Deadline.subject_id.in_(subject_ids)),
                    and_(Deadline.is_personal.is_(True), Deadline.author_id == user_id),
                ),
            )
            .order_by(Deadline.due_at, Deadline.id)
        )
        return result.all()

    async def list_manageable(
        self, user_id: int, after: datetime, *, admin: bool
    ) -> Sequence[Deadline]:
        """Что пользователь может изменить или удалить: свои дедлайны; админ — ещё и все общие."""
        own = Deadline.author_id == user_id
        condition = or_(own, Deadline.is_personal.is_(False)) if admin else own
        result = await self.session.scalars(
            select(Deadline)
            .where(Deadline.deleted_at.is_(None), Deadline.due_at > after, condition)
            .order_by(Deadline.due_at, Deadline.id)
        )
        return result.all()

    async def list_duplicate_candidates(
        self, subject_id: int, due_at: datetime
    ) -> Sequence[Deadline]:
        """Общие дедлайны того же предмета со сроком в пределах суток."""
        result = await self.session.scalars(
            select(Deadline).where(
                Deadline.subject_id == subject_id,
                Deadline.is_personal.is_(False),
                Deadline.deleted_at.is_(None),
                Deadline.due_at.between(due_at - DUE_WINDOW, due_at + DUE_WINDOW),
            )
        )
        return result.all()

    async def soft_delete(self, deadline: Deadline) -> None:
        deadline.deleted_at = utcnow()
        await self.session.flush()

    async def completed_ids(self, user_id: int, deadline_ids: set[int]) -> set[int]:
        if not deadline_ids:
            return set()
        result = await self.session.scalars(
            select(Completion.deadline_id).where(
                Completion.user_id == user_id, Completion.deadline_id.in_(deadline_ids)
            )
        )
        return set(result.all())
