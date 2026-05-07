import uuid

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.auth_context import AuthenticatedUser
from app.core.cache import CacheService
from app.core.exceptions import BusinessRuleError
from app.modules.identity.service import IdentityService
from app.modules.reporting.schemas import FirmReportResponse, GlobalReportItem, GlobalReportResponse
from app.modules.summarization.service import SummaryStatsService


class ReportingService:
    """Report generation with short-lived Redis caching."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        cache: CacheService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.cache = cache or CacheService()
        self.settings = settings or get_settings()
        self.identity = IdentityService(session)
        self.summaries = SummaryStatsService(session)

    async def firm_report(
        self,
        *,
        current_user: AuthenticatedUser,
        firm_id: uuid.UUID | None = None,
    ) -> FirmReportResponse:
        resolved_firm_id = firm_id if current_user.role == "superuser" else current_user.firm_id
        if resolved_firm_id is None:
            raise BusinessRuleError("firm_id is required for superuser firm report")
        cache_key = f"report:firm:{resolved_firm_id}"
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return FirmReportResponse.model_validate(cached)

        clients_with_summaries, total_emails, last_activity = await self.summaries.firm_summary_totals(
            resolved_firm_id
        )
        response = FirmReportResponse(
            firm_id=resolved_firm_id,
            clients_with_summaries=clients_with_summaries,
            total_emails_analyzed=total_emails,
            last_activity=last_activity,
        )
        await self._set_cached(cache_key, response.model_dump(mode="json"))
        return response

    async def global_report(self, *, page: int, page_size: int) -> GlobalReportResponse:
        cache_key = f"report:global:page:{page}:size:{page_size}"
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return GlobalReportResponse.model_validate(cached)

        total = await self.identity.count_firms()
        firms = await self.identity.list_firms(page=page, page_size=page_size)
        totals = await self.summaries.summary_totals_by_firm([firm.id for firm in firms])
        response = GlobalReportResponse(
            items=[
                GlobalReportItem(
                    firm_id=firm.id,
                    firm_name=firm.name,
                    clients_with_summaries=totals.get(firm.id, (0, 0, None))[0],
                    total_emails_analyzed=totals.get(firm.id, (0, 0, None))[1],
                    last_activity=totals.get(firm.id, (0, 0, None))[2],
                )
                for firm in firms
            ],
            page=page,
            page_size=page_size,
            total=total,
        )
        await self._set_cached(cache_key, response.model_dump(mode="json"))
        return response

    async def _get_cached(self, key: str) -> dict | None:
        try:
            value = await self.cache.get_json(key)
        except RedisError:
            return None
        return value if isinstance(value, dict) else None

    async def _set_cached(self, key: str, value: dict) -> None:
        try:
            await self.cache.set_json(key, value, self.settings.cache_report_ttl_seconds)
        except RedisError:
            return
