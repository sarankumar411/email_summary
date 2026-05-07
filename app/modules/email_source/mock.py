import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.email_source.interface import EmailMessage, EmailSourceService
from app.modules.email_source.models import Email


class MockEmailService(EmailSourceService):
    """Mock email provider backed by seeded database rows.

    Replaces the real Microsoft Graph API integration for the case study.
    Implements the EmailSourceService ABC, so SummarizationService is unaware
    of the concrete provider — swapping to Graph API requires no consumer changes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_emails_for_client(self, client_id: uuid.UUID) -> int:
        """Count all email rows for a client without loading their bodies (cheap check).

        Query:
            SELECT count(id) FROM emails WHERE client_id = :client_id

        Used by SummarizationService to decide whether to skip a refresh when no
        new emails have arrived since the last summarisation.

        Dry run:
            client_id=UUID("cli-1"), 12 rows in emails table → 12
            client_id=UUID("new-0"), 0 rows → 0
        """
        result = await self.session.scalar(
            select(func.count(Email.id)).where(Email.client_id == client_id)
        )
        return int(result or 0)

    async def fetch_emails_for_client(self, client_id: uuid.UUID) -> list[EmailMessage]:
        """Load all email rows for a client and convert them to provider-neutral EmailMessage objects.

        Query:
            SELECT * FROM emails
            WHERE client_id = :client_id
            ORDER BY sent_at ASC, thread_id ASC

        Primary sort by sent_at ensures chronological order for coherent summarisation.
        Secondary sort by thread_id provides a stable tie-break within the same timestamp
        (e.g., multiple emails sent in the same second).

        EmailMessage is a frozen dataclass defined in email_source/interface.py — it contains
        no SQLAlchemy references, making it safe to pass across module boundaries.

        Dry run:
            client_id=UUID("cli-1"), 3 seeded emails
            → [
                EmailMessage(subject="Tax filing Q1", sent_at=datetime(2025-01-10), ...),
                EmailMessage(subject="Re: Tax filing Q1", sent_at=datetime(2025-01-12), ...),
                EmailMessage(subject="Audit docs request", sent_at=datetime(2025-02-01), ...),
              ]
        """
        result = await self.session.execute(
            select(Email)
            .where(Email.client_id == client_id)
            .order_by(Email.sent_at.asc(), Email.thread_id.asc())
        )
        return [
            EmailMessage(
                id=email.id,
                client_id=email.client_id,
                sender_accountant_id=email.sender_accountant_id,
                sender_email=email.sender_email,
                recipients=email.recipients,
                cc=email.cc,
                thread_id=email.thread_id,
                subject=email.subject,
                body=email.body,
                sent_at=email.sent_at,
                direction=email.direction.value,
            )
            for email in result.scalars().all()
        ]
