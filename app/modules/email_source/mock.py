import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.email_source.interface import EmailMessage, EmailSourceService
from app.modules.email_source.models import Email


class MockEmailService(EmailSourceService):
    """Mock email provider backed by seeded database rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_emails_for_client(self, client_id: uuid.UUID) -> int:
        result = await self.session.scalar(
            select(func.count(Email.id)).where(Email.client_id == client_id)
        )
        return int(result or 0)

    async def fetch_emails_for_client(self, client_id: uuid.UUID) -> list[EmailMessage]:
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
