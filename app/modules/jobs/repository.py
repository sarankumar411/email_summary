import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job, JobStatus, JobType


class JobsRepository:
    """Persistence operations for background jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_refresh_job(
        self,
        *,
        client_id: uuid.UUID,
        triggered_by_accountant_id: uuid.UUID,
        expires_at: datetime,
    ) -> Job:
        """Insert a new job row in 'queued' status and return it with a DB-assigned UUID.

        The job row is the source of truth for lifecycle state exposed via GET /jobs/{id}.
        expires_at = now() + 24 h so the periodic Celery beat task can prune stale rows.
        flush() is called immediately so the UUID is populated before the row is returned;
        commit() is deferred to JobsService.enqueue_refresh() after the Celery task is fired.

        Dry run:
            client_id=UUID("cli-1"), triggered_by=UUID("acc-1"),
            expires_at=datetime(2025-04-01, 14:00, UTC)
            → Job(id=UUID("new-uuid"), status=JobStatus.queued, started_at=None,
                  completed_at=None, result=None)
        """
        job = Job(
            job_type=JobType.refresh_summary,
            client_id=client_id,
            triggered_by_accountant_id=triggered_by_accountant_id,
            status=JobStatus.queued,
            expires_at=expires_at,
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def get_job(self, job_id: uuid.UUID) -> Job | None:
        """Fetch a job by primary key. Returns None for expired, deleted, or non-existent jobs.

        Query:
            SELECT * FROM jobs WHERE id = :job_id

        Dry run:
            job_id=UUID("job-1") → Job(status=JobStatus.completed, result={...})
            job_id=UUID("old-1") → None  (already pruned by the cleanup beat task)
        """
        result = await self.session.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()

    async def set_running(self, job_id: uuid.UUID) -> None:
        """Transition a job to 'running' and stamp started_at with the current UTC time.

        Query:
            UPDATE jobs
            SET status = 'running', started_at = now()
            WHERE id = :job_id

        Called at the very start of the Celery task, before any DB or Gemini work begins,
        so the caller can observe the transition via GET /jobs/{id}.
        """
        await self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=JobStatus.running, started_at=datetime.now(UTC))
        )

    async def set_completed(
        self,
        job_id: uuid.UUID,
        *,
        status: JobStatus,
        result: dict,
        error_message: str | None = None,
    ) -> None:
        """Transition a job to a terminal state and stamp completed_at.

        Terminal states: JobStatus.completed, JobStatus.failed, JobStatus.skipped.
        result is stored as JSONB and exposed verbatim via GET /jobs/{id}.

        Query:
            UPDATE jobs
            SET status=:status, result=:result,
                error_message=:error_message, completed_at=now()
            WHERE id = :job_id

        Dry run (success):
            status=JobStatus.completed,
            result={"status":"completed","client_id":"...","emails_analyzed_count":15},
            error_message=None.
        Dry run (failure):
            status=JobStatus.failed,
            result={"status":"failed","client_id":"..."},
            error_message="gemini unavailable".
        Dry run (skipped, no new emails):
            status=JobStatus.skipped,
            result={"status":"skipped_no_new_emails","client_id":"...","emails_analyzed_count":8}.
        """
        await self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=status,
                result=result,
                error_message=error_message,
                completed_at=datetime.now(UTC),
            )
        )

    async def delete_expired(self) -> int:
        """Hard-delete all job rows where expires_at < now(). Returns the number of rows deleted.

        Query:
            DELETE FROM jobs WHERE expires_at < now()

        Called hourly by the Celery beat task (cleanup_expired_jobs_task).
        Jobs are created with expires_at = created_at + 24 h, so this cleans up
        anything older than a day.

        Dry run: 7 job rows have expires_at in the past → deletes all 7, returns 7.
        Dry run: no expired rows → returns 0.
        """
        result = await self.session.execute(delete(Job).where(Job.expires_at < datetime.now(UTC)))
        return int(cast(Any, result).rowcount or 0)
