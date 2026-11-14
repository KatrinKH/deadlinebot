"""Загрузка начальных предметов и треков из seed.yaml."""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Subject, Track, TrackChoiceGroup, User
from bot.db.repositories.subscriptions import SubscriptionRepo

logger = logging.getLogger(__name__)


class SeedTrack(BaseModel):
    name: str
    mandatory: list[str] = []
    # Группы «выбери один»: [[Python, Java], [Переговоры, Публичные выступления]]
    choose_one: list[list[str]] = []
    # Недоступные студентам трека — не показываются в выборе предметов
    hidden: list[str] = []

    def all_subject_names(self) -> set[str]:
        return set(self.mandatory).union(*self.choose_one, self.hidden)


class SeedData(BaseModel):
    # Раздел → список предметов. Порядок разделов в файле = порядок в меню бота.
    subjects: dict[str, list[str]]
    tracks: list[SeedTrack]

    @model_validator(mode="after")
    def _validate(self) -> "SeedData":
        self.subjects = {
            category.strip(): [name.strip() for name in names if name and name.strip()]
            for category, names in self.subjects.items()
        }
        seen: set[str] = set()
        for names in self.subjects.values():
            for name in names:
                if name in seen:
                    raise ValueError(f"Предмет «{name}» указан в seed.yaml дважды")
                seen.add(name)

        for track in self.tracks:
            unknown = track.all_subject_names() - seen
            if unknown:
                raise ValueError(
                    f"Трек «{track.name}» ссылается на предметы, которых нет "
                    f"в разделе subjects: {sorted(unknown)}"
                )
            for group in track.choose_one:
                if len(set(group)) < 2:
                    raise ValueError(
                        f"Трек «{track.name}»: в группе choose_one нужно минимум "
                        f"два разных предмета, а указано {group}"
                    )
            options = [n for group in track.choose_one for n in group]
            used = [*track.mandatory, *options, *track.hidden]
            repeated = {n for n in used if used.count(n) > 1}
            if repeated:
                raise ValueError(
                    f"Трек «{track.name}»: предметы повторяются в mandatory/choose_one/hidden: "
                    f"{sorted(repeated)}"
                )
        return self

    def iter_subjects(self):
        """Пары (категория, название) в порядке файла."""
        for category, names in self.subjects.items():
            for name in names:
                yield category, name


def load_seed_file(path: str | Path) -> SeedData:
    with open(path, encoding="utf-8") as f:
        return SeedData.model_validate(yaml.safe_load(f))


async def apply_seed(session: AsyncSession, data: SeedData, sync_tracks: bool = True) -> None:
    """Загружает seed.yaml в БД.

    Недостающие предметы и треки всегда добавляются. Предметы и треки,
    которых нет в файле, не удаляются — по ним могут быть дедлайны.
    При `sync_tracks=True` существующие треки и разделы предметов приводятся
    к файлу, а подписки студентов этих треков — к обновлённым трекам.
    """
    subjects = await _sync_subjects(session, data, update_categories=sync_tracks)

    tracks = {t.name: t for t in (await session.scalars(select(Track))).all()}
    added, updated = 0, 0
    for seed_track in data.tracks:
        track = tracks.get(seed_track.name)
        if track is None:
            track = Track(name=seed_track.name, mandatory_subjects=[], hidden_subjects=[])
            _fill_track(track, seed_track, subjects)
            session.add(track)
            added += 1
        elif sync_tracks and await _sync_track(session, track, seed_track, subjects):
            updated += 1

    await session.commit()
    logger.info("Seed applied: +%d tracks, %d tracks updated", added, updated)


async def _sync_subjects(
    session: AsyncSession, data: SeedData, update_categories: bool
) -> dict[str, Subject]:
    existing = {s.name: s for s in (await session.scalars(select(Subject))).all()}
    added = 0
    for category, name in data.iter_subjects():
        subject = existing.get(name)
        if subject is None:
            existing[name] = Subject(name=name, category=category)
            session.add(existing[name])
            added += 1
        elif update_categories and subject.category != category:
            logger.info("Subject %r moved to category %r", name, category)
            subject.category = category
    await session.flush()
    if added:
        logger.info("Seed: +%d subjects", added)
    return existing


def _fill_track(track: Track, seed_track: SeedTrack, subjects: dict[str, Subject]) -> None:
    track.mandatory_subjects = [subjects[n] for n in seed_track.mandatory]
    track.hidden_subjects = [subjects[n] for n in seed_track.hidden]
    track.choice_groups = [
        TrackChoiceGroup(position=i, options=[subjects[n] for n in group])
        for i, group in enumerate(seed_track.choose_one)
    ]


def _track_signature(track: Track) -> tuple:
    """Состав трека в сравнимом виде: обязательные, группы «выбери один», скрытые."""
    groups = tuple(frozenset(s.id for s in g.options) for g in track.choice_groups)
    return track.fixed_ids(), groups, track.hidden_ids()


async def _sync_track(
    session: AsyncSession, track: Track, seed_track: SeedTrack, subjects: dict[str, Subject]
) -> bool:
    """Приводит трек к seed.yaml. Возвращает True, если что-то изменилось."""
    wanted = (
        {subjects[n].id for n in seed_track.mandatory},
        tuple(frozenset(subjects[n].id for n in group) for group in seed_track.choose_one),
        {subjects[n].id for n in seed_track.hidden},
    )
    if _track_signature(track) == wanted:
        return False

    previous_ids = track.subject_ids()
    groups_changed = _track_signature(track)[1] != wanted[1]
    track.mandatory_subjects = [subjects[n] for n in seed_track.mandatory]
    track.hidden_subjects = [subjects[n] for n in seed_track.hidden]
    if groups_changed:  # пересоздаём группы только при изменении, чтобы не сбивать их id
        track.choice_groups = [
            TrackChoiceGroup(position=i, options=[subjects[n] for n in group])
            for i, group in enumerate(seed_track.choose_one)
        ]
    await session.flush()

    # Студенты трека получают новые обязательные предметы и теряют убранные
    user_ids = (await session.scalars(select(User.id).where(User.track_id == track.id))).all()
    repo = SubscriptionRepo(session)
    for user_id in user_ids:
        await repo.reconcile_track(user_id, previous_ids, track)
    logger.info("Track %r updated from seed, %d users resynced", track.name, len(user_ids))
    return True
