import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.jobs.models import JobStatus, JobType


class JobCreateResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: JobType
    client_id: uuid.UUID | None
    triggered_by_accountant_id: uuid.UUID
    status: JobStatus
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime

