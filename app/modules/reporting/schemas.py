import uuid
from datetime import datetime

from pydantic import BaseModel


class FirmReportResponse(BaseModel):
    firm_id: uuid.UUID
    clients_with_summaries: int
    total_emails_analyzed: int
    last_activity: datetime | None


class GlobalReportItem(BaseModel):
    firm_id: uuid.UUID
    firm_name: str
    clients_with_summaries: int
    total_emails_analyzed: int
    last_activity: datetime | None


class GlobalReportResponse(BaseModel):
    items: list[GlobalReportItem]
    page: int
    page_size: int
    total: int

