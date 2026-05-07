import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import AuthenticatedUser
from app.modules.clients.models import AccountantClientAssignment, Client, ClientEmail


class ClientsRepository:
    """Persistence operations for clients, emails, and assignments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_client(self, client_id: uuid.UUID) -> Client | None:
        result = await self.session.execute(select(Client).where(Client.id == client_id))
        return result.scalar_one_or_none()

    async def list_clients_for_user(
        self,
        user: AuthenticatedUser,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Client], int]:
        stmt = select(Client)
        count_stmt = select(func.count(Client.id))

        if user.role == "accountant":
            stmt = stmt.join(
                AccountantClientAssignment,
                AccountantClientAssignment.client_id == Client.id,
            ).where(AccountantClientAssignment.accountant_id == user.id)
            count_stmt = count_stmt.join(
                AccountantClientAssignment,
                AccountantClientAssignment.client_id == Client.id,
            ).where(AccountantClientAssignment.accountant_id == user.id)
        elif user.role == "admin":
            stmt = stmt.where(Client.firm_id == user.firm_id)
            count_stmt = count_stmt.where(Client.firm_id == user.firm_id)

        stmt = stmt.order_by(Client.full_name).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        total = await self.session.scalar(count_stmt)
        return list(result.scalars().all()), int(total or 0)

    async def email_addresses_for_clients(self, client_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        if not client_ids:
            return {}
        result = await self.session.execute(
            select(ClientEmail.client_id, ClientEmail.email_address)
            .where(ClientEmail.client_id.in_(client_ids))
            .order_by(ClientEmail.is_primary.desc(), ClientEmail.email_address)
        )
        grouped: dict[uuid.UUID, list[str]] = {client_id: [] for client_id in client_ids}
        for client_id, email in result.all():
            grouped.setdefault(client_id, []).append(email)
        return grouped

    async def is_assigned(self, accountant_id: uuid.UUID, client_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(AccountantClientAssignment).where(
                AccountantClientAssignment.accountant_id == accountant_id,
                AccountantClientAssignment.client_id == client_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def replace_assignments(
        self,
        *,
        accountant_id: uuid.UUID,
        client_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        await self.session.execute(
            delete(AccountantClientAssignment).where(
                AccountantClientAssignment.accountant_id == accountant_id
            )
        )
        for client_id in sorted(set(client_ids)):
            self.session.add(
                AccountantClientAssignment(
                    accountant_id=accountant_id,
                    client_id=client_id,
                )
            )
        await self.session.flush()
        return sorted(set(client_ids))

    async def remove_assignment(self, accountant_id: uuid.UUID, client_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(AccountantClientAssignment).where(
                AccountantClientAssignment.accountant_id == accountant_id,
                AccountantClientAssignment.client_id == client_id,
            )
        )

    async def current_assignment_ids(self, accountant_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(AccountantClientAssignment.client_id)
            .where(AccountantClientAssignment.accountant_id == accountant_id)
            .order_by(AccountantClientAssignment.client_id)
        )
        return list(result.scalars().all())
