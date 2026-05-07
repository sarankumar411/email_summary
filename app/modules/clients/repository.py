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
        """Fetch a single client by primary key. Returns None if not found.

        Query:
            SELECT * FROM clients WHERE id = :client_id

        Dry run:
            client_id = UUID("abc-1") → Client(full_name="Acme Corp", firm_id=UUID("f-1"))
            client_id = UUID("000-0") → None
        """
        result = await self.session.execute(select(Client).where(Client.id == client_id))
        return result.scalar_one_or_none()

    async def list_clients_for_user(
        self,
        user: AuthenticatedUser,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Client], int]:
        """Return a paginated, alphabetically sorted list of clients visible to the caller.

        Authorization branching applied at the query level:
            - accountant : INNER JOIN accountant_client_assignments on client_id,
                           WHERE accountant_id = user.id.
                           Only clients explicitly assigned to this user are returned.
            - admin      : WHERE clients.firm_id = user.firm_id.
                           All firm clients; no join needed.
            - superuser  : No WHERE clause — sees every client across all firms.

        Two queries run per call: one for the page data and one for the total COUNT so the
        caller can render pagination controls. Both use identical JOIN/WHERE conditions to
        keep the total consistent with the page.

        Dry run (accountant assigned to 2 clients, page=1, page_size=10):
            → ([Client("Acme"), Client("Beta")], 2)
        Dry run (admin, firm has 30 clients, page=2, page_size=10):
            → ([Client(...) × 10], 30)   # second page of results, total=30
        Dry run (superuser, page=1, page_size=5, platform has 120 clients):
            → ([Client(...) × 5], 120)
        """
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
        """Bulk-fetch all email addresses for a list of clients in a single round-trip.

        Query:
            SELECT client_id, email_address
            FROM client_emails
            WHERE client_id IN (:client_ids)
            ORDER BY is_primary DESC, email_address ASC

        Primary addresses sort first (is_primary=True → 1 DESC → first); secondary addresses
        follow alphabetically within each client group. Pre-fills every requested client_id
        with an empty list so callers get a key for every client, even those with no emails.
        Early-returns an empty dict when client_ids is empty to avoid a vacuous IN () query.

        Dry run:
            client_ids = [UUID("aaa"), UUID("bbb")]
            → {
                UUID("aaa"): ["primary@acme.com", "secondary@acme.com"],
                UUID("bbb"): ["contact@beta.com"],
              }
        Dry run (no emails registered for a client):
            → {UUID("ccc"): []}
        """
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
        """Return True if an assignment row exists for this (accountant, client) pair.

        Query:
            SELECT * FROM accountant_client_assignments
            WHERE accountant_id = :accountant_id AND client_id = :client_id

        Dry run:
            (accountant_id=UUID("acc-1"), client_id=UUID("cli-1")) → True   (row exists)
            (accountant_id=UUID("acc-1"), client_id=UUID("cli-9")) → False  (no row)
        """
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
        """Atomically replace all assignments for one accountant (idempotent full replace).

        Logic:
            1. DELETE all existing rows WHERE accountant_id = :id (bulk, no per-row check).
            2. INSERT one new row per unique client_id (sorted for deterministic order).
            3. Flush to Postgres within the current transaction — caller must commit.

        Deduplication: set(client_ids) ensures duplicate UUIDs in the input are collapsed.
        Sorting: sorted() produces a stable INSERT order, making the result list deterministic.

        Dry run (accountant previously assigned to [A, B, C], called with [B, D]):
            → DELETE rows for A, B, C; INSERT rows for B, D.
            → Returns [UUID("B"), UUID("D")] sorted.
        Dry run (client_ids=[]):
            → DELETE all; nothing inserted; returns [].
        """
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
        """Delete a single assignment row. Silent no-op if the row does not exist.

        Query:
            DELETE FROM accountant_client_assignments
            WHERE accountant_id = :accountant_id AND client_id = :client_id

        Dry run:
            Row exists  → deleted, rowcount=1.
            Row missing → no error, rowcount=0.
        """
        await self.session.execute(
            delete(AccountantClientAssignment).where(
                AccountantClientAssignment.accountant_id == accountant_id,
                AccountantClientAssignment.client_id == client_id,
            )
        )

    async def current_assignment_ids(self, accountant_id: uuid.UUID) -> list[uuid.UUID]:
        """Return all client IDs currently assigned to an accountant, sorted for determinism.

        Query:
            SELECT client_id FROM accountant_client_assignments
            WHERE accountant_id = :accountant_id
            ORDER BY client_id

        Dry run:
            accountant assigned to UUID("bbb") and UUID("aaa")
            → [UUID("aaa"), UUID("bbb")]  (sorted ascending)
        Dry run (no assignments):
            → []
        """
        result = await self.session.execute(
            select(AccountantClientAssignment.client_id)
            .where(AccountantClientAssignment.accountant_id == accountant_id)
            .order_by(AccountantClientAssignment.client_id)
        )
        return list(result.scalars().all())
