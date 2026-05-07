import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import CurrentUser, ReadDb
from app.modules.jobs.schemas import JobOut
from app.modules.jobs.service import JobsService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_jobs_read_service(session: ReadDb) -> JobsService:
    return JobsService(session)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    service: Annotated[JobsService, Depends(get_jobs_read_service)],
) -> JobOut:
    job = await service.get_visible_job(job_id, current_user)
    return JobOut.model_validate(job)
