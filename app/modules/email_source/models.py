import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB_COMPAT, Base, UUIDPrimaryKeyMixin


class EmailDirection(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class Email(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "emails"
    __table_args__ = (
        Index("ix_emails_client_sent_at", "client_id", "sent_at"),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id"),
        nullable=False,
        index=True,
    )
    sender_accountant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accountants.id"),
        nullable=True,
    )
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB_COMPAT, nullable=False)
    cc: Mapped[list[str]] = mapped_column(JSONB_COMPAT, nullable=False, default=list, server_default="[]")
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    direction: Mapped[EmailDirection] = mapped_column(
        Enum(EmailDirection, name="email_direction"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
