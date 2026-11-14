"""Логика предметов пользователя.

У каждого студента три вида предметов:
- обязательные трека — подписка добавляется автоматически, снять нельзя;
- обязательные «на выбор» — из группы (например, Python или Java) студент выбирает один;
- по выбору — факультативы, soft skills, интенсивы и т.п., отмечает сам.
Предметы из списка «скрытых» трека студенту не показываются вовсе.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Subject, Track, TrackChoiceGroup, User
from bot.db.repositories import CatalogRepo, SubscriptionRepo


@dataclass(frozen=True)
class SubjectGroup:
    """Раздел меню выбора: например, «Факультативы» и его предметы."""

    name: str
    subjects: Sequence[Subject]


def group_by_category(subjects: Sequence[Subject]) -> list[SubjectGroup]:
    """Группирует предметы по разделам.

    Разделы идут в порядке появления в seed.yaml (по наименьшему id предмета),
    предметы внутри раздела — по алфавиту.
    """
    groups: dict[str, list[Subject]] = {}
    for subject in sorted(subjects, key=lambda s: s.id):
        groups.setdefault(subject.category, []).append(subject)
    return [
        SubjectGroup(name, sorted(items, key=lambda s: s.name)) for name, items in groups.items()
    ]


@dataclass(frozen=True)
class ChoiceState:
    """Группа «выбери один» и что в ней выбрал студент."""

    group_id: int
    options: Sequence[Subject]
    chosen: Subject | None  # None — ещё не выбрал (или подписан сразу на несколько)

    @property
    def title(self) -> str:
        return " или ".join(s.name for s in self.options)


@dataclass(frozen=True)
class UserSubjects:
    fixed: Sequence[Subject]  # обязательные трека
    choices: Sequence[ChoiceState]  # обязательные «на выбор»
    electives: Sequence[Subject]  # доступные по выбору
    selected_elective_ids: set[int]  # предметы по выбору, на которые подписан студент

    @property
    def mandatory(self) -> list[Subject]:
        """Все обязательные: трека + выбранные в группах «выбери один»."""
        chosen = [c.chosen for c in self.choices if c.chosen is not None]
        return sorted([*self.fixed, *chosen], key=lambda s: s.name)

    @property
    def subscribed(self) -> list[Subject]:
        """Все предметы, на которые подписан студент: обязательные и выбранные."""
        chosen = [s for s in self.electives if s.id in self.selected_elective_ids]
        return sorted([*self.mandatory, *chosen], key=lambda s: s.name)

    @property
    def unresolved_choices(self) -> list[ChoiceState]:
        return [c for c in self.choices if c.chosen is None]

    def choice(self, group_id: int) -> ChoiceState | None:
        return next((c for c in self.choices if c.group_id == group_id), None)

    @property
    def elective_groups(self) -> list[SubjectGroup]:
        return group_by_category(self.electives)

    def selected_groups(self, selected_ids: set[int] | None = None) -> list[SubjectGroup]:
        """Только выбранные предметы по выбору, по разделам; пустые разделы отбрасываются."""
        ids = self.selected_elective_ids if selected_ids is None else selected_ids
        return group_by_category([s for s in self.electives if s.id in ids])


def _active(subjects: Sequence[Subject]) -> list[Subject]:
    return [s for s in subjects if s.is_active]


def _choice_state(group: TrackChoiceGroup, subscribed_ids: set[int]) -> ChoiceState:
    options = _active(group.options)
    picked = [s for s in options if s.id in subscribed_ids]
    return ChoiceState(group.id, options, picked[0] if len(picked) == 1 else None)


def split_subjects(
    all_subjects: Sequence[Subject], track: Track | None, subscribed_ids: set[int]
) -> UserSubjects:
    """Раскладывает предметы пользователя по видам. Чистая функция — удобно тестировать."""
    if track is None:
        fixed, choices, hidden_ids = [], [], set()
    else:
        fixed = _active(track.mandatory_subjects)
        choices = [_choice_state(g, subscribed_ids) for g in track.choice_groups]
        choices = [c for c in choices if c.options]
        hidden_ids = {s.id for s in track.hidden_subjects}

    track_ids = {s.id for s in fixed} | {s.id for c in choices for s in c.options}
    electives = [s for s in all_subjects if s.id not in track_ids | hidden_ids]
    selected = {s.id for s in electives if s.id in subscribed_ids}
    return UserSubjects(fixed, choices, electives, selected)


async def load_user_subjects(session: AsyncSession, user: User) -> UserSubjects:
    all_subjects = await CatalogRepo(session).list_subjects()
    subscribed = await SubscriptionRepo(session).get_subject_ids(user.id)
    return split_subjects(all_subjects, user.track, subscribed)


@dataclass
class SubjectsDraft:
    """Несохранённые изменения в /subjects: применяются только кнопкой «Сохранить».

    Хранится в FSM-данных пользователя, поэтому умеет превращаться в dict и обратно.
    """

    electives: set[int] = field(default_factory=set)
    choices: dict[int, int] = field(default_factory=dict)  # группа «выбери один» → предмет

    @classmethod
    def from_subjects(cls, subjects: UserSubjects) -> "SubjectsDraft":
        return cls(
            electives=set(subjects.selected_elective_ids),
            choices={c.group_id: c.chosen.id for c in subjects.choices if c.chosen},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "electives": sorted(self.electives),
            "choices": {str(k): v for k, v in self.choices.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubjectsDraft":
        return cls(
            electives=set(data.get("electives", [])),
            choices={int(k): v for k, v in data.get("choices", {}).items()},
        )


def with_draft(subjects: UserSubjects, draft: SubjectsDraft) -> UserSubjects:
    """Как выглядели бы предметы пользователя, если сохранить черновик."""
    choices = []
    for c in subjects.choices:
        picked = next((s for s in c.options if s.id == draft.choices.get(c.group_id)), c.chosen)
        choices.append(replace(c, chosen=picked))
    valid_electives = {s.id for s in subjects.electives}
    return replace(
        subjects, choices=choices, selected_elective_ids=draft.electives & valid_electives
    )


def draft_changes(subjects: UserSubjects, draft: SubjectsDraft) -> bool:
    """Отличается ли черновик от сохранённого состояния."""
    return SubjectsDraft.from_subjects(with_draft(subjects, draft)) != SubjectsDraft.from_subjects(
        subjects
    )


async def apply_draft(
    session: AsyncSession, user: User, subjects: UserSubjects, draft: SubjectsDraft
) -> bool:
    """Сохраняет черновик в подписки. Возвращает True, если что-то изменилось."""
    target = with_draft(subjects, draft)
    repo = SubscriptionRepo(session)
    added = target.selected_elective_ids - subjects.selected_elective_ids
    removed = subjects.selected_elective_ids - target.selected_elective_ids
    await repo.subscribe(user.id, added)
    await repo.unsubscribe(user.id, removed)

    changed = bool(added or removed)
    catalog = CatalogRepo(session)
    for before, after in zip(subjects.choices, target.choices, strict=True):
        if after.chosen and (before.chosen is None or before.chosen.id != after.chosen.id):
            group = await catalog.get_choice_group(after.group_id)
            if group is not None:
                await repo.choose_option(user.id, group, after.chosen.id)
                changed = True
    return changed
