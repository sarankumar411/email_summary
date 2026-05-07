import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, PrimaryKeyConstraint, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "clients"

    firm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("firms.id"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)


class ClientEmail(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "client_emails"
    __table_args__ = (
        UniqueConstraint("client_id", "email_address", name="uq_client_emails_client_email"),
        UniqueConstraint("firm_id", "email_address", name="uq_client_emails_firm_email"),
        Index("ix_client_emails_email_address", "email_address"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("firms.id"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AccountantClientAssignment(Base):
    __tablename__ = "accountant_client_assignments"
    __table_args__ = (
        PrimaryKeyConstraint("accountant_id", "client_id", name="pk_accountant_client_assignments"),
        Index("ix_accountant_client_assignments_accountant_id", "accountant_id"),
        Index("ix_accountant_client_assignments_client_id", "client_id"),
    )

    accountant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accountants.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
