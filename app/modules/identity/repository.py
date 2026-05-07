import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Accountant, Firm


class IdentityRepository:
    """Persistence operations for firms and accountants."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_accountant_by_email(self, email: str) -> Accountant | None:
        result = await self.session.execute(
            select(Accountant).where(Accountant.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_accountant_by_id(self, accountant_id: uuid.UUID) -> Accountant | None:
        result = await self.session.execute(
            select(Accountant).where(Accountant.id == accountant_id)
        )
        return result.scalar_one_or_none()

    async def get_firm_by_id(self, firm_id: uuid.UUID) -> Firm | None:
        result = await self.session.execute(select(Firm).where(Firm.id == firm_id))
        return result.scalar_one_or_none()

    async def count_firms(self) -> int:
        result = await self.session.scalar(select(func.count(Firm.id)))
        return int(result or 0)

    async def list_firms(self, *, page: int, page_size: int) -> list[Firm]:
        result = await self.session.execute(
            select(Firm).order_by(Firm.name.asc()).offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all())

    async def update_accountant(
        self,
        accountant: Accountant,
        *,
        full_name: str | None = None,
        is_active: bool | None = None,
    ) -> Accountant:
        if full_name is not None:
            accountant.full_name = full_name
        if is_active is not None:
            accountant.is_active = is_active
        await self.session.flush()
        await self.session.refresh(accountant)
        return accountant
