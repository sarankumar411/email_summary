import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import AuthenticatedUser, RoleName
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import create_access_token, verify_password
from app.modules.identity.models import Accountant, Role
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import AccountantUpdateRequest


@dataclass(frozen=True, slots=True)
class FirmContext:
    """Firm metadata exposed through the identity service interface."""

    id: uuid.UUID
    name: str


class IdentityService:
    """Identity use cases such as login and accountant profile updates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = IdentityRepository(session)

    async def authenticate(self, email: str, password: str) -> tuple[str, int]:
        """Verify credentials and return a signed JWT token with its lifetime in seconds.

        Logic:
            1. Look up accountant by email (lower-cased at DB level).
            2. Raise AuthorizationError if the account does not exist or is inactive —
               both cases return the same error to prevent user enumeration.
            3. Verify the plaintext password against the stored bcrypt hash.
            4. Issue a JWT with claims: sub=accountant.id, firm_id, role, iat, exp, jti.

        Returns (access_token: str, expires_in: int) where expires_in is seconds.

        Dry run (valid credentials):
            email="priya@cpafirm.com", password="correct-password"
            → ("eyJ...", 3600)
        Dry run (wrong password or unknown email):
            → raises AuthorizationError("Invalid credentials")
        Dry run (inactive account):
            → raises AuthorizationError("Invalid credentials")  (same message, no leakage)
        """
        accountant = await self.repository.get_accountant_by_email(email)
        if accountant is None or not accountant.is_active:
            raise AuthorizationError("Invalid credentials")
        if not verify_password(password, accountant.password_hash):
            raise AuthorizationError("Invalid credentials")
        return create_access_token(
            subject=accountant.id,
            firm_id=accountant.firm_id,
            role=accountant.role.value,
        )

    async def get_accountant_context(self, accountant_id: uuid.UUID) -> AuthenticatedUser | None:
        """Return a module-safe user context for authorization decisions."""

        accountant = await self.repository.get_accountant_by_id(accountant_id)
        if accountant is None:
            return None
        return self._to_context(accountant)

    async def get_active_accountant_context(self, accountant_id: uuid.UUID) -> AuthenticatedUser | None:
        """Return active user context or None when the account is inactive/missing."""

        context = await self.get_accountant_context(accountant_id)
        if context is None or not context.is_active:
            return None
        return context

    async def count_firms(self) -> int:
        """Count firms for paginated platform reports."""

        return await self.repository.count_firms()

    async def list_firms(self, *, page: int, page_size: int) -> list[FirmContext]:
        """List firms sorted by name for platform reports."""

        firms = await self.repository.list_firms(page=page, page_size=page_size)
        return [FirmContext(id=firm.id, name=firm.name) for firm in firms]

    async def update_accountant(
        self,
        accountant_id: uuid.UUID,
        payload: AccountantUpdateRequest,
        current_user: AuthenticatedUser,
    ) -> Accountant:
        """Patch full_name and/or is_active on an accountant; enforces ownership and role rules.

        Authorization rules (enumeration-resistant — all violations raise NotFoundError):
            - accountant : can only edit their own profile (current_user.id == target.id).
            - admin      : can edit any accountant within their own firm only.
            - superuser  : can edit anyone (no additional check).

        Additional rule: only admins and superusers may change is_active.
        A regular accountant attempting to set is_active raises AuthorizationError (403),
        which is intentional — we want the caller to know they lack the role, not that the
        record doesn't exist.

        Dry run (accountant editing own name):
            accountant_id=current_user.id, payload.full_name="Priya K.", payload.is_active=None
            → returns updated Accountant with full_name="Priya K.".
        Dry run (admin deactivating a cross-firm accountant):
            → raises NotFoundError (enumeration resistance).
        Dry run (accountant trying to set is_active=False on self):
            → raises AuthorizationError("Only admins can change active status").
        """
        target = await self.repository.get_accountant_by_id(accountant_id)
        if target is None:
            raise NotFoundError("Accountant not found")

        if current_user.role == Role.accountant and current_user.id != target.id:
            raise NotFoundError("Accountant not found")
        if current_user.role == Role.admin and current_user.firm_id != target.firm_id:
            raise NotFoundError("Accountant not found")
        if payload.is_active is not None and current_user.role == Role.accountant:
            raise AuthorizationError("Only admins can change active status")

        updated = await self.repository.update_accountant(
            target,
            full_name=payload.full_name,
            is_active=payload.is_active,
        )
        await self.session.commit()
        return updated

    def _to_context(self, accountant: Accountant) -> AuthenticatedUser:
        """Convert a SQLAlchemy Accountant ORM object to a module-safe AuthenticatedUser dataclass.

        The AuthenticatedUser dataclass is used throughout the service and dependency layers
        so that modules never hold a reference to the raw ORM model (which is tied to a session).

        Dry run:
            accountant.id=UUID("acc-1"), accountant.role=Role.admin
            → AuthenticatedUser(id=UUID("acc-1"), role="admin", is_active=True, ...)
        """
        return AuthenticatedUser(
            id=accountant.id,
            firm_id=accountant.firm_id,
            email=accountant.email,
            full_name=accountant.full_name,
            role=cast(RoleName, accountant.role.value),
            is_active=accountant.is_active,
        )
