import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    firm_id: uuid.UUID
    full_name: str
    email_addresses: list[EmailStr]
    created_at: datetime
    updated_at: datetime


class ClientListResponse(BaseModel):
    items: list[ClientOut]
    page: int
    page_size: int
    total: int

