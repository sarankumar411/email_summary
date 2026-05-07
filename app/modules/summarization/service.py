import uuid
from datetime import UTC, datetime
from time import perf_counter

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.cache import CacheService
from app.core.encryption import EncryptionService
from app.core.exceptions import NotFoundError
from app.modules.clients.service import ClientsService
from app.modules.email_source.interface import EmailSourceService
from app.modules.email_source.mock import MockEmailService
from app.modules.jobs.service import JobsService
from app.modules.summarization.gemini_client import GeminiClient
from app.modules.summarization.models import RefreshAuditStatus
from app.modules.summarization.repository import SummarizationRepository
from app.modules.summarization.schemas import GeminiSummarySchema, SummaryResponse
from app.observability.metrics import (
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
    REFRESH_JOBS_TOTAL,
    SUMMARIZATION_DURATION_SECONDS,
)


class SummarizationService:
    """Refresh and read encrypted email summaries."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        email_source: EmailSourceService | None = None,
        gemini_client: GeminiClient | None = None,
        encryption_service: EncryptionService | None = None,
        cache_service: CacheService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.repository = SummarizationRepository(session)
        self.clients_service = ClientsService(session)
        self.jobs_service = JobsService(session)
        self.email_source = email_source or MockEmailService(session)
        self.gemini_client = gemini_client or GeminiClient()
        self.encryption_service = encryption_service or EncryptionService()
        self.cache = cache_service or CacheService()
        self.settings = settings or get_settings()

    async def get_summary(self, client_id: uuid.UUID) -> SummaryResponse:
        cache_key = self._summary_cache_key(client_id)
        try:
            cached = await self.cache.get_json(cache_key)
        except RedisError:
            cached = None
        if isinstance(cached, dict):
            CACHE_HITS_TOTAL.inc()
            return SummaryResponse.model_validate(cached)
        CACHE_MISSES_TOTAL.inc()

        summary = await self.repository.get_summary_by_client(client_id)
        if summary is None:
            raise NotFoundError("Summary not found")

        payload = self.encryption_service.decrypt_json(
            summary.encrypted_payload,
            summary.encryption_nonce,
            summary.encryption_key_version,
        )
        response = SummaryResponse(
            client_id=summary.client_id,
            emails_analyzed_count=summary.emails_analyzed_count,
            last_refreshed_at=summary.last_refreshed_at,
            gemini_model_version=summary.gemini_model_version,
            **payload,
        )
        await self._cache_summary(response)
        return response

    async def refresh_summary(
        self,
        *,
        job_id: uuid.UUID | None,
        client_id: uuid.UUID,
        triggered_by_accountant_id: uuid.UUID,
        force: bool,
    ) -> dict:
        start = perf_counter()
        existing_summary_id: uuid.UUID | None = None
        emails_processed = 0
        if job_id is not None:
            await self.jobs_service.mark_running(job_id)
            await self.session.commit()

        try:
            await self._acquire_advisory_lock(client_id)
            client = await self.clients_service.get_client_context(client_id)
            if client is None:
                raise NotFoundError("Client not found")

            existing = await self.repository.get_summary_by_client(client_id)
            existing_summary_id = existing.id if existing is not None else None
            email_count = await self.email_source.count_emails_for_client(client_id)
            if existing is not None and email_count == existing.emails_analyzed_count and not force:
                duration_ms = self._elapsed_ms(start)
                await self.repository.create_audit_log(
                    summary_id=existing.id,
                    client_id=client_id,
                    triggered_by_accountant_id=triggered_by_accountant_id,
                    duration_ms=duration_ms,
                    emails_processed=0,
                    status=RefreshAuditStatus.skipped_no_new_emails,
                )
                if job_id is not None:
                    await self.jobs_service.mark_completed(
                        job_id,
                        status="skipped",
                        result={
                            "status": "skipped_no_new_emails",
                            "client_id": str(client_id),
                            "emails_analyzed_count": existing.emails_analyzed_count,
                        },
                    )
                await self.session.commit()
                REFRESH_JOBS_TOTAL.labels("skipped").inc()
                return {"status": "skipped_no_new_emails", "client_id": str(client_id)}

            emails = await self.email_source.fetch_emails_for_client(client_id)
            emails_processed = email_count
            generated = await self._summarize_with_map_reduce(emails)
            now = datetime.now(UTC)
            encrypted = self.encryption_service.encrypt_json(generated.model_dump(mode="json"))
            summary = await self.repository.upsert_summary(
                client_id=client_id,
                firm_id=client.firm_id,
                encrypted_payload=encrypted.ciphertext,
                encryption_nonce=encrypted.nonce,
                encryption_key_version=encrypted.key_version,
                emails_analyzed_count=email_count,
                last_refreshed_at=now,
                gemini_model_version=self.settings.gemini_model,
            )
            response = SummaryResponse(
                client_id=client_id,
                emails_analyzed_count=email_count,
                last_refreshed_at=now,
                gemini_model_version=self.settings.gemini_model,
                **generated.model_dump(),
            )
            await self.repository.create_audit_log(
                summary_id=summary.id,
                client_id=client_id,
                triggered_by_accountant_id=triggered_by_accountant_id,
                duration_ms=self._elapsed_ms(start),
                emails_processed=email_count,
                status=RefreshAuditStatus.success,
            )
            await self._cache_summary(response)
            if job_id is not None:
                await self.jobs_service.mark_completed(
                    job_id,
                    status="completed",
                    result={
                        "status": "completed",
                        "client_id": str(client_id),
                        "summary_id": str(summary.id),
                        "emails_analyzed_count": email_count,
                    },
                )
            await self.session.commit()
            REFRESH_JOBS_TOTAL.labels("completed").inc()
            SUMMARIZATION_DURATION_SECONDS.observe(perf_counter() - start)
            return {"status": "completed", "client_id": str(client_id), "summary_id": str(summary.id)}
        except Exception as exc:
            await self.session.rollback()
            try:
                await self.repository.create_audit_log(
                    summary_id=existing_summary_id,
                    client_id=client_id,
                    triggered_by_accountant_id=triggered_by_accountant_id,
                    duration_ms=self._elapsed_ms(start),
                    emails_processed=emails_processed,
                    status=RefreshAuditStatus.failed,
                    error_message=str(exc),
                )
                await self.session.commit()
            except Exception:
                await self.session.rollback()
            if job_id is not None:
                try:
                    await self.jobs_service.mark_completed(
                        job_id,
                        status="failed",
                        result={"status": "failed", "client_id": str(client_id)},
                        error_message=str(exc),
                    )
                    await self.session.commit()
                except Exception:
                    await self.session.rollback()
            REFRESH_JOBS_TOTAL.labels("failed").inc()
            raise

    async def firm_summary_totals(self, firm_id: uuid.UUID) -> tuple[int, int, datetime | None]:
        """Return summary totals for one firm."""

        return await self.repository.firm_report(firm_id)

    async def summary_totals_by_firm(
        self,
        firm_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[int, int, datetime | None]]:
        """Return summary totals keyed by firm id."""

        return await self.repository.firm_reports(firm_ids)

    async def _summarize_with_map_reduce(self, emails: list) -> GeminiSummarySchema:
        threshold = self.settings.summary_chunk_threshold
        if len(emails) <= threshold:
            return await self.gemini_client.summarize_emails(emails)

        partials: list[GeminiSummarySchema] = []
        for index in range(0, len(emails), threshold):
            partials.append(await self.gemini_client.summarize_emails(emails[index : index + threshold]))
        return await self.gemini_client.merge_summaries(partials)

    async def _acquire_advisory_lock(self, client_id: uuid.UUID) -> None:
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        await self.session.execute(
            text("select pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"summary:{client_id}"},
        )

    async def _cache_summary(self, response: SummaryResponse) -> None:
        try:
            await self.cache.set_json(
                self._summary_cache_key(response.client_id),
                response.model_dump(mode="json"),
                self.settings.cache_summary_ttl_seconds,
            )
        except RedisError:
            return

    def _summary_cache_key(self, client_id: uuid.UUID) -> str:
        return f"summary:client:{client_id}"

    def _elapsed_ms(self, start: float) -> int:
        return int((perf_counter() - start) * 1000)


class SummaryStatsService:
    """Read-only summary statistics exposed to reporting."""

    def __init__(self, session: AsyncSession) -> None:
        self.repository = SummarizationRepository(session)

    async def firm_summary_totals(self, firm_id: uuid.UUID) -> tuple[int, int, datetime | None]:
        """Return summary totals for one firm."""

        return await self.repository.firm_report(firm_id)

    async def summary_totals_by_firm(
        self,
        firm_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[int, int, datetime | None]]:
        """Return summary totals keyed by firm id."""

        return await self.repository.firm_reports(firm_ids)
