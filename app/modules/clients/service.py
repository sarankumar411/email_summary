import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import AuthenticatedUser
from app.core.exceptions import NotFoundError
from app.modules.clients.repository import ClientsRepository
from app.modules.clients.schemas import ClientListResponse, ClientOut
from app.modules.identity.service import IdentityService


@dataclass(frozen=True, slots=True)
class ClientContext:
    """Client metadata exposed through the clients service interface."""

    id: uuid.UUID
    firm_id: uuid.UUID
    full_name: str
    created_at: datetime
    updated_at: datetime


class ClientsService:
    """Client access and assignment use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ClientsRepository(session)
        self.identity_service = IdentityService(session)

    async def list_clients(
        self,
        user: AuthenticatedUser,
        *,
        page: int,
        page_size: int,
    ) -> ClientListResponse:
        """Return a paginated list of clients the caller is authorised to see, with email addresses.

        Delegates visibility filtering to the repository (accountant sees assigned only; admin
        sees firm clients; superuser sees all). Then bulk-fetches email addresses for the returned
        page in a single second query to avoid N+1 per-client lookups.

        Dry run (accountant, 2 assigned clients, page=1, page_size=10):
            → ClientListResponse(items=[ClientOut("Acme"), ClientOut("Beta")], total=2)
        Dry run (admin, 30 firm clients, page=2, page_size=10):
            → ClientListResponse(items=[...10 clients...], page=2, total=30)
        """
        clients, total = await self.repository.list_clients_for_user(
            user,
            page=page,
            page_size=page_size,
        )
        email_map = await self.repository.email_addresses_for_clients([client.id for client in clients])
        return ClientListResponse(
            items=[
                ClientOut(
                    id=client.id,
                    firm_id=client.firm_id,
                    full_name=client.full_name,
                    email_addresses=email_map.get(client.id, []),
                    created_at=client.created_at,
                    updated_at=client.updated_at,
                )
                for client in clients
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_client_context(self, client_id: uuid.UUID) -> ClientContext | None:
        """Return client metadata without exposing the ORM model to other modules.

        Used internally by SummarizationService and JobsService to look up a client's
        firm_id for tenant-isolation checks. Returns None instead of raising so callers
        can decide how to handle a missing client.

        Dry run:
            client_id=UUID("cli-1") → ClientContext(id=..., firm_id=UUID("f-1"), ...)
            client_id=UUID("000-0") → None
        """
        client = await self.repository.get_client(client_id)
        if client is None:
            return None
        return ClientContext(
            id=client.id,
            firm_id=client.firm_id,
            full_name=client.full_name,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )

    async def get_accessible_client(self, client_id: uuid.UUID, user: AuthenticatedUser) -> ClientContext:
        """Return a ClientContext if the caller can access this client; raise NotFoundError otherwise.

        This is the main authorization gate for client-scoped endpoints (GET summary, POST refresh).
        All unauthorized cases raise NotFoundError (404) rather than 403 to prevent enumeration:
        a caller cannot distinguish "this client doesn't exist" from "it exists but you can't see it".

        Access rules:
            - superuser  : always granted.
            - admin      : granted when client.firm_id == user.firm_id.
            - accountant : granted when an assignment row exists for (user.id, client_id).

        Dry run (admin, same firm):
            → ClientContext(id=UUID("cli-1"), firm_id=UUID("f-1"), ...)
        Dry run (accountant, not assigned):
            → raises NotFoundError("Client not found")  — 404
        Dry run (admin, different firm's client):
            → raises NotFoundError("Client not found")  — 404
        """
        client = await self.repository.get_client(client_id)
        if client is None:
            raise NotFoundError("Client not found")
        context = ClientContext(
            id=client.id,
            firm_id=client.firm_id,
            full_name=client.full_name,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )
        if user.role == "superuser":
            return context
        if user.role == "admin" and client.firm_id == user.firm_id:
            return context
        if user.role == "accountant" and await self.repository.is_assigned(user.id, client_id):
            return context
        raise NotFoundError("Client not found")

    async def get_client_detail(self, client_id: uuid.UUID, user: AuthenticatedUser) -> ClientOut:
        """Return a full ClientOut DTO (with email addresses) if the caller can access this client.

        Calls get_accessible_client first to enforce AuthZ, then fetches email addresses
        for the single client. Used by GET /clients/{client_id}.

        Dry run (accountant assigned to client):
            → ClientOut(full_name="Acme Corp",
                        email_addresses=["primary@acme.com", "alt@acme.com"])
        Dry run (not assigned):
            → raises NotFoundError → 404
        """
        client = await self.get_accessible_client(client_id, user)
        email_map = await self.repository.email_addresses_for_clients([client.id])
        return ClientOut(
            id=client.id,
            firm_id=client.firm_id,
            full_name=client.full_name,
            email_addresses=email_map.get(client.id, []),
            created_at=client.created_at,
            updated_at=client.updated_at,
        )

    async def replace_assignments(
        self,
        *,
        target_accountant_id: uuid.UUID,
        client_ids: list[uuid.UUID],
        current_user: AuthenticatedUser,
    ) -> list[uuid.UUID]:
        """Idempotently replace all client assignments for an accountant.

        AuthZ (enumeration-resistant):
            - Admin can only reassign accountants and clients within their own firm.
            - Superuser has no firm restriction.
            All out-of-scope cases raise NotFoundError (404) to prevent enumeration.

        Logic:
            1. Verify the target accountant exists and is accessible to the caller.
            2. Verify every client_id in the list exists and is accessible to the caller.
            3. Delegate the atomic DELETE + INSERT to the repository.
            4. Commit the transaction.

        Dry run (admin, same firm, client_ids=[UUID("cli-1"), UUID("cli-2")]):
            → [UUID("cli-1"), UUID("cli-2")]  (sorted, deduplicated)
        Dry run (admin targeting cross-firm accountant):
            → raises NotFoundError
        Dry run (client_ids=[]):
            → clears all assignments, returns []
        """
        target = await self.identity_service.get_accountant_context(target_accountant_id)
        if target is None:
            raise NotFoundError("Accountant not found")
        if current_user.role == "admin" and target.firm_id != current_user.firm_id:
            raise NotFoundError("Accountant not found")

        for client_id in client_ids:
            client = await self.repository.get_client(client_id)
            if client is None:
                raise NotFoundError("Client not found")
            if current_user.role == "admin" and client.firm_id != current_user.firm_id:
                raise NotFoundError("Client not found")

        assignments = await self.repository.replace_assignments(
            accountant_id=target_accountant_id,
            client_ids=client_ids,
        )
        await self.session.commit()
        return assignments

    async def remove_assignment(
        self,
        *,
        accountant_id: uuid.UUID,
        client_id: uuid.UUID,
        current_user: AuthenticatedUser,
    ) -> None:
        """Remove a single (accountant, client) assignment, enforcing firm-level isolation.

        AuthZ (enumeration-resistant):
            - Admin: both the target accountant and the client must belong to the admin's firm.
            - Superuser: no firm restriction.
            Missing accountant, missing client, or cross-firm access all raise NotFoundError.

        Dry run (admin, same firm):
            accountant_id=UUID("acc-1"), client_id=UUID("cli-1")
            → assignment row deleted; 204 returned to caller.
        Dry run (admin, cross-firm accountant):
            → raises NotFoundError("Assignment not found")
        """
        target = await self.identity_service.get_accountant_context(accountant_id)
        client = await self.repository.get_client(client_id)
        if target is None or client is None:
            raise NotFoundError("Assignment not found")
        if current_user.role == "admin" and (
            target.firm_id != current_user.firm_id or client.firm_id != current_user.firm_id
        ):
            raise NotFoundError("Assignment not found")
        await self.repository.remove_assignment(accountant_id, client_id)
        await self.session.commit()
