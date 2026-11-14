from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.base import utcnow
from bot.db.models import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def upsert(self, user_id: int, full_name: str, username: str | None) -> User:
        """Создаёт пользователя или обновляет имя и время последней активности."""
        user = await self.get(user_id)
        if user is None:
            user = User(id=user_id, full_name=full_name, username=username)
            self.session.add(user)
        else:
            user.full_name = full_name
            user.username = username
            user.last_active_at = utcnow()
        await self.session.flush()
        return user

    async def set_track(self, user: User, track_id: int) -> None:
        user.track_id = track_id
        await self.session.flush()
        await self.session.refresh(user, ["track"])

    async def mark_onboarded(self, user: User) -> None:
        user.is_onboarded = True
        await self.session.flush()

    async def count_subject_change(self, user: User) -> None:
        user.subject_changes_used += 1
        await self.session.flush()

    async def grant_subject_change(self, user: User) -> None:
        user.subject_changes_granted += 1
        await self.session.flush()
