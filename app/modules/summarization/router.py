import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.exceptions import NotFoundError
from app.deps import CurrentUser, ReadDb, WriteDb, get_clients_read_service
from app.modules.clients.service import ClientsService
from app.modules.jobs.schemas import JobCreateResponse
from app.modules.jobs.service import JobsService
from app.modules.summarization.schemas import RefreshSummaryRequest, SummaryResponse
from app.modules.summarization.service import SummarizationService

router = APIRouter(prefix="/clients/{client_id}/summary", tags=["summaries"])


def get_summarization_read_service(session: ReadDb) -> SummarizationService:
    return SummarizationService(session)


def get_jobs_write_service(session: WriteDb) -> JobsService:
    return JobsService(session)


@router.get("", response_model=SummaryResponse)
async def get_summary(
    client_id: uuid.UUID,
    current_user: CurrentUser,
    clients_service: Annotated[ClientsService, Depends(get_clients_read_service)],
    service: Annotated[SummarizationService, Depends(get_summarization_read_service)],
) -> SummaryResponse:
    await clients_service.get_accessible_client(client_id, current_user)
    try:
        return await service.get_summary(client_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found") from exc


@router.post("/refresh", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def refresh_summary(
    client_id: uuid.UUID,
    current_user: CurrentUser,
    clients_service: Annotated[ClientsService, Depends(get_clients_read_service)],
    jobs_service: Annotated[JobsService, Depends(get_jobs_write_service)],
    payload: Annotated[RefreshSummaryRequest | None, Body()] = None,
) -> JobCreateResponse:
    await clients_service.get_accessible_client(client_id, current_user)
    job = await jobs_service.enqueue_refresh(
        client_id=client_id,
        triggered_by=current_user,
        force=payload.force if payload is not None else False,
    )
    return JobCreateResponse(job_id=job.id, status=job.status)
