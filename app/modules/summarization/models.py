import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RefreshAuditStatus(StrEnum):
    success = "success"
    skipped_no_new_emails = "skipped_no_new_emails"
    failed = "failed"


class EmailSummary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_summaries"

    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    firm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("firms.id"),
        nullable=False,
        index=True,
    )
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    emails_analyzed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    gemini_model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class RefreshAuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "refresh_audit_log"
    __table_args__ = (
        CheckConstraint(
            "summary_id IS NOT NULL OR status = 'failed'",
            name="ck_refresh_audit_log_summary_required_unless_failed",
        ),
    )

    summary_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("email_summaries.id"),
        nullable=True,
        index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id"),
        nullable=False,
        index=True,
    )
    triggered_by_accountant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accountants.id"),
        nullable=False,
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emails_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[RefreshAuditStatus] = mapped_column(
        Enum(RefreshAuditStatus, name="refresh_audit_status"),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
