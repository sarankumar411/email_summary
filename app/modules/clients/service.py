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
        """Return client metadata without exposing the clients table model."""

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
