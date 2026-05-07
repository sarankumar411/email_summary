import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.exceptions import BusinessRuleError
from app.deps import AdminUser, ReadDb, Superuser
from app.modules.reporting.schemas import FirmReportResponse, GlobalReportResponse
from app.modules.reporting.service import ReportingService

router = APIRouter(prefix="/reports", tags=["reports"])


def get_reporting_service(session: ReadDb) -> ReportingService:
    return ReportingService(session)


@router.get("/firm", response_model=FirmReportResponse)
async def get_firm_report(
    current_user: AdminUser,
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    firm_id: uuid.UUID | None = None,
) -> FirmReportResponse:
    try:
        return await service.firm_report(current_user=current_user, firm_id=firm_id)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/global", response_model=GlobalReportResponse)
async def get_global_report(
    current_user: Superuser,
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> GlobalReportResponse:
    del current_user
    return await service.global_report(page=page, page_size=page_size)

