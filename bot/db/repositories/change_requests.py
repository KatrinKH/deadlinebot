"""Запросы студентов к админу на изменение предметов."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.base import utcnow
from bot.db.models import ChangeRequest, ChangeRequestStatus


class ChangeRequestRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: int, text: str) -> ChangeRequest:
        request = ChangeRequest(user_id=user_id, text=text)
        self.session.add(request)
        await self.session.flush()
        await self.session.refresh(request, ["user"])
        return request

    async def get(self, request_id: int) -> ChangeRequest | None:
        return await self.session.get(ChangeRequest, request_id)

    async def get_open_for_user(self, user_id: int) -> ChangeRequest | None:
        return await self.session.scalar(
            select(ChangeRequest)
            .where(
                ChangeRequest.user_id == user_id,
                ChangeRequest.status == ChangeRequestStatus.OPEN,
            )
            .limit(1)
        )

    async def resolve(self, request: ChangeRequest, status: ChangeRequestStatus) -> None:
        request.status = status
        request.resolved_at = utcnow()
        await self.session.flush()
