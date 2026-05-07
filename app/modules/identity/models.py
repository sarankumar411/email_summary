import uuid
from enum import StrEnum

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(StrEnum):
    accountant = "accountant"
    admin = "admin"
    superuser = "superuser"


class Firm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "firms"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    accountants: Mapped[list["Accountant"]] = relationship(back_populates="firm")


class Accountant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "accountants"
    __table_args__ = (
        Index("ix_accountants_firm_role", "firm_id", "role"),
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("firms.id"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="accountant_role"),
        nullable=False,
        default=Role.accountant,
        server_default=Role.accountant.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    firm: Mapped[Firm] = relationship(back_populates="accountants")
