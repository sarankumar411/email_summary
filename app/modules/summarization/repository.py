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
        """Fetch the encrypted summary row for a client, or None if no refresh has run yet.

        Query:
            SELECT * FROM email_summaries WHERE client_id = :client_id

        Dry run:
            client_id = UUID("a1b2-...") → EmailSummary(emails_analyzed_count=12, ...)
            client_id = UUID("new-...")  → None  (first-time client, no summary yet)
        """
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
        """Insert a new summary row or overwrite every mutable column of the existing one.

        Logic:
            1. SELECT the row by client_id (one extra read per refresh, acceptable given
               refresh is a low-frequency write path).
            2. Missing → INSERT a fresh EmailSummary and flush to obtain the server UUID.
            3. Present → mutate fields in-place; SQLAlchemy's unit-of-work emits an UPDATE
               on flush without needing an explicit UPDATE statement.

        Session.commit() is intentionally left to the caller (SummarizationService) so the
        upsert and the audit-log INSERT share a single atomic transaction.

        Dry run (first refresh):
            client_id=UUID("cli-1") not found → INSERT, returns EmailSummary(id=UUID("new-uuid")).
        Dry run (re-refresh):
            existing row found → overwrite payload, nonce, count=15, returns same id.
        """
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
        """Append one row to refresh_audit_log for every refresh attempt.

        Called unconditionally — for successes, skips, and hard failures — so the audit
        trail is complete regardless of outcome. summary_id is nullable because a failure
        before the first upsert means no EmailSummary row exists yet.

        Dry run (success):
            status=RefreshAuditStatus.success, emails_processed=15, duration_ms=1240
            → inserts row; error_message=None.
        Dry run (skip, no new emails):
            status=RefreshAuditStatus.skipped_no_new_emails, emails_processed=0
            → inserts row; duration_ms reflects the advisory-lock + count-check time only.
        Dry run (failure):
            status=RefreshAuditStatus.failed, error_message="gemini unavailable"
            → inserts row; summary_id=None if failure occurred before first upsert.
        """
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
        """Aggregate summary statistics for a single firm in one DB round-trip.

        Query:
            SELECT count(client_id),
                   coalesce(sum(emails_analyzed_count), 0),
                   max(last_refreshed_at)
            FROM email_summaries
            WHERE firm_id = :firm_id

        Returns (clients_with_summaries, total_emails_analyzed, last_activity).
        coalesce ensures sum returns 0 instead of NULL when no rows match.

        Dry run:
            firm_id = UUID("firm-1")
            → (3, 47, datetime(2025, 3, 20, 14, 0, tzinfo=UTC))
              3 clients summarised, 47 emails total, last refresh on 20 Mar 2025.
        Dry run (firm with no summaries yet):
            → (0, 0, None)
        """
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
        """Batch aggregation for multiple firms in a single query (used by the global report).

        Query:
            SELECT firm_id,
                   count(client_id),
                   coalesce(sum(emails_analyzed_count), 0),
                   max(last_refreshed_at)
            FROM email_summaries
            WHERE firm_id IN (:firm_ids)
            GROUP BY firm_id

        Firms that have no summary rows are absent from the result dict entirely.
        Callers should use .get(firm_id, (0, 0, None)) to handle the missing-firm case.
        Early-returns an empty dict when firm_ids is empty to avoid a vacuous IN () query.

        Dry run:
            firm_ids = [UUID("aaa"), UUID("bbb"), UUID("ccc")]
            → {
                UUID("aaa"): (2, 30, datetime(2025-03-18, ...)),
                UUID("bbb"): (1,  5, datetime(2025-03-01, ...)),
                # UUID("ccc") has no summaries — absent from the dict
              }
        """
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
