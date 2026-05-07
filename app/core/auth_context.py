import uuid
from dataclasses import dataclass
from typing import Literal

RoleName = Literal["accountant", "admin", "superuser"]


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Minimal authenticated-user context shared across modules."""

    id: uuid.UUID
    firm_id: uuid.UUID
    email: str
    full_name: str
    role: RoleName
    is_active: bool

