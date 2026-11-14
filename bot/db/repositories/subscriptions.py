"""Подписки пользователей на предметы."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Subject, Subscription, Track, TrackChoiceGroup


class SubscriptionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_subject_ids(self, user_id: int) -> set[int]:
        result = await self.session.scalars(
            select(Subscription.subject_id)
            .join(Subject, Subject.id == Subscription.subject_id)
            .where(Subscription.user_id == user_id, Subject.is_active.is_(True))
        )
        return set(result.all())

    async def get_subscriber_ids(self, subject_id: int) -> set[int]:
        result = await self.session.scalars(
            select(Subscription.user_id).where(Subscription.subject_id == subject_id)
        )
        return set(result.all())

    async def subscribe(self, user_id: int, subject_ids: set[int]) -> None:
        existing = await self.get_subject_ids(user_id)
        for subject_id in subject_ids - existing:
            self.session.add(Subscription(user_id=user_id, subject_id=subject_id))
        await self.session.flush()

    async def unsubscribe(self, user_id: int, subject_ids: set[int]) -> None:
        if not subject_ids:
            return
        await self.session.execute(
            delete(Subscription).where(
                Subscription.user_id == user_id, Subscription.subject_id.in_(subject_ids)
            )
        )
        await self.session.flush()

    async def switch_track(self, user_id: int, old: Track | None, new: Track) -> None:
        """Смена трека: подписки приводятся к новому треку."""
        await self.reconcile_track(user_id, old.subject_ids() if old else set(), new)

    async def reconcile_track(self, user_id: int, previous_ids: set[int], track: Track) -> None:
        """Приводит подписки пользователя к треку.

        `previous_ids` — предметы, которые раньше относились к треку пользователя
        (старого трека при смене или прежняя версия трека после обновления seed.yaml).
        Убираем те из них, что больше не входят в трек, и недоступные в треке;
        подписываем на обязательные. Подписки на варианты «выбери один» сохраняем:
        если студент уже изучает Python, выбор «Python или Java» решится сам.
        Остальные предметы по выбору не трогаем.
        """
        await self.unsubscribe(user_id, (previous_ids - track.subject_ids()) | track.hidden_ids())
        await self.subscribe(user_id, track.fixed_ids())

    async def choose_option(self, user_id: int, group: TrackChoiceGroup, subject_id: int) -> None:
        """Выбор в группе «выбери один»: подписываем на выбранный, отписываем от остальных."""
        option_ids = {s.id for s in group.options}
        await self.unsubscribe(user_id, option_ids - {subject_id})
        await self.subscribe(user_id, {subject_id})
