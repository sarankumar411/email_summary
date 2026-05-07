import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Provider-neutral email record used by summarization consumers."""

    id: uuid.UUID
    client_id: uuid.UUID
    sender_accountant_id: uuid.UUID | None
    sender_email: str
    recipients: list[str]
    cc: list[str]
    thread_id: str
    subject: str
    body: str
    sent_at: datetime
    direction: str


class EmailSourceService(ABC):
    """Interface for any email provider implementation."""

    @abstractmethod
    async def count_emails_for_client(self, client_id: uuid.UUID) -> int:
        raise NotImplementedError

    @abstractmethod
    async def fetch_emails_for_client(self, client_id: uuid.UUID) -> list[EmailMessage]:
        raise NotImplementedError
