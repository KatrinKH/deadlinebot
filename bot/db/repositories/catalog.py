"""Справочники: треки и предметы."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Subject, Track, TrackChoiceGroup


class CatalogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_tracks(self) -> Sequence[Track]:
        result = await self.session.scalars(select(Track).order_by(Track.id))
        return result.all()

    async def get_track(self, track_id: int) -> Track | None:
        return await self.session.get(Track, track_id)

    async def get_choice_group(self, group_id: int) -> TrackChoiceGroup | None:
        return await self.session.get(TrackChoiceGroup, group_id)

    async def list_subjects(self, *, active_only: bool = True) -> Sequence[Subject]:
        stmt = select(Subject).order_by(Subject.name)
        if active_only:
            stmt = stmt.where(Subject.is_active.is_(True))
        result = await self.session.scalars(stmt)
        return result.all()

    async def get_subject(self, subject_id: int) -> Subject | None:
        return await self.session.get(Subject, subject_id)

    async def get_subjects_by_ids(self, subject_ids: set[int]) -> Sequence[Subject]:
        if not subject_ids:
            return []
        result = await self.session.scalars(
            select(Subject).where(Subject.id.in_(subject_ids)).order_by(Subject.name)
        )
        return result.all()
