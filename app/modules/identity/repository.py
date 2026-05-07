import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Accountant, Firm


class IdentityRepository:
    """Persistence operations for firms and accountants."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_accountant_by_email(self, email: str) -> Accountant | None:
        """Look up an accountant by email address, normalised to lower-case before comparison.

        Normalisation prevents login from failing when the user types mixed-case email.
        The accountants.email column is stored lower-case at INSERT time, so the comparison
        is always apples-to-apples.

        Query:
            SELECT * FROM accountants WHERE email = lower(:email)

        Dry run:
            email="Priya@CPAFirm.COM" → Accountant(email="priya@cpafirm.com", role=Role.admin)
            email="nobody@example.com" → None
        """
        result = await self.session.execute(
            select(Accountant).where(Accountant.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_accountant_by_id(self, accountant_id: uuid.UUID) -> Accountant | None:
        """Fetch an accountant by UUID primary key. Returns None if not found.

        Query:
            SELECT * FROM accountants WHERE id = :accountant_id

        Dry run:
            accountant_id=UUID("acc-1") → Accountant(full_name="Priya Sharma", is_active=True)
            accountant_id=UUID("000-0") → None
        """
        result = await self.session.execute(
            select(Accountant).where(Accountant.id == accountant_id)
        )
        return result.scalar_one_or_none()

    async def get_firm_by_id(self, firm_id: uuid.UUID) -> Firm | None:
        """Fetch a firm by UUID primary key. Returns None if not found.

        Query:
            SELECT * FROM firms WHERE id = :firm_id
        """
        result = await self.session.execute(select(Firm).where(Firm.id == firm_id))
        return result.scalar_one_or_none()

    async def count_firms(self) -> int:
        """Count total firms for pagination metadata in the global superuser report.

        Query:
            SELECT count(id) FROM firms

        Dry run: 3 firms seeded → 3
        Dry run: no firms → 0  (coerced from None via `or 0`)
        """
        result = await self.session.scalar(select(func.count(Firm.id)))
        return int(result or 0)

    async def list_firms(self, *, page: int, page_size: int) -> list[Firm]:
        """Return a page of firms sorted alphabetically by name.

        Query:
            SELECT * FROM firms
            ORDER BY name ASC
            LIMIT :page_size OFFSET (:page - 1) * :page_size

        Dry run (firms=["Alpha CPA", "Beta Partners", "Gamma LLC"], page=2, page_size=2):
            → [Firm(name="Gamma LLC")]   # third firm, second page of size-2
        Dry run (page=1, page_size=25, only 3 firms):
            → [Firm("Alpha CPA"), Firm("Beta Partners"), Firm("Gamma LLC")]
        """
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
        """Patch mutable fields on an Accountant ORM object; only provided (non-None) fields change.

        Only full_name and is_active are patchable here; role changes require a separate
        admin-only flow that is out of scope for this endpoint.
        SQLAlchemy's unit-of-work emits a targeted UPDATE on flush without an explicit
        UPDATE statement — only dirty columns are written.

        Dry run:
            full_name="Priya Sharma", is_active=None
            → sets full_name; is_active column unchanged.
        Dry run:
            full_name=None, is_active=False
            → deactivates account; full_name column unchanged.
        """
        if full_name is not None:
            accountant.full_name = full_name
        if is_active is not None:
            accountant.is_active = is_active
        await self.session.flush()
        await self.session.refresh(accountant)
        return accountant
