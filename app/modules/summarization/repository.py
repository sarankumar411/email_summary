import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.summarization.models import EmailSummary, RefreshAuditLog, RefreshAuditStatus


class SummarizationRepository:
    """Persistence operations for encrypted summaries and refresh audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_summary_by_client(self, client_id: uuid.UUID) -> EmailSummary | None:
        result = await self.session.execute(
            select(EmailSummary).where(EmailSummary.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def upsert_summary(
        self,
        *,
        client_id: uuid.UUID,
        firm_id: uuid.UUID,
        encrypted_payload: bytes,
        encryption_nonce: bytes,
        encryption_key_version: int,
        emails_analyzed_count: int,
        last_refreshed_at: datetime,
        gemini_model_version: str,
    ) -> EmailSummary:
        summary = await self.get_summary_by_client(client_id)
        if summary is None:
            summary = EmailSummary(
                client_id=client_id,
                firm_id=firm_id,
                encrypted_payload=encrypted_payload,
                encryption_nonce=encryption_nonce,
                encryption_key_version=encryption_key_version,
                emails_analyzed_count=emails_analyzed_count,
                last_refreshed_at=last_refreshed_at,
                gemini_model_version=gemini_model_version,
            )
            self.session.add(summary)
        else:
            summary.encrypted_payload = encrypted_payload
            summary.encryption_nonce = encryption_nonce
            summary.encryption_key_version = encryption_key_version
            summary.emails_analyzed_count = emails_analyzed_count
            summary.last_refreshed_at = last_refreshed_at
            summary.gemini_model_version = gemini_model_version
        await self.session.flush()
        await self.session.refresh(summary)
        return summary

    async def create_audit_log(
        self,
        *,
        summary_id: uuid.UUID | None,
        client_id: uuid.UUID,
        triggered_by_accountant_id: uuid.UUID,
        duration_ms: int | None,
        emails_processed: int,
        status: RefreshAuditStatus,
        error_message: str | None = None,
    ) -> RefreshAuditLog:
        row = RefreshAuditLog(
            summary_id=summary_id,
            client_id=client_id,
            triggered_by_accountant_id=triggered_by_accountant_id,
            duration_ms=duration_ms,
            emails_processed=emails_processed,
            status=status,
            error_message=error_message,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def firm_report(self, firm_id: uuid.UUID) -> tuple[int, int, datetime | None]:
        result = await self.session.execute(
            select(
                func.count(EmailSummary.client_id),
                func.coalesce(func.sum(EmailSummary.emails_analyzed_count), 0),
                func.max(EmailSummary.last_refreshed_at),
            ).where(EmailSummary.firm_id == firm_id)
        )
        clients_with_summaries, total_emails, last_activity = result.one()
        return int(clients_with_summaries), int(total_emails), last_activity

    async def firm_reports(
        self,
        firm_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[int, int, datetime | None]]:
        if not firm_ids:
            return {}

        result = await self.session.execute(
            select(
                EmailSummary.firm_id,
                func.count(EmailSummary.client_id),
                func.coalesce(func.sum(EmailSummary.emails_analyzed_count), 0),
                func.max(EmailSummary.last_refreshed_at),
            )
            .where(EmailSummary.firm_id.in_(firm_ids))
            .group_by(EmailSummary.firm_id)
        )
        return {
            firm_id: (int(clients_with_summaries), int(total_emails), last_activity)
            for firm_id, clients_with_summaries, total_emails, last_activity in result.all()
        }
