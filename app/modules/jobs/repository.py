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
        result = await self.session.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()

    async def set_running(self, job_id: uuid.UUID) -> None:
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
        result = await self.session.execute(delete(Job).where(Job.expires_at < datetime.now(UTC)))
        return int(cast(Any, result).rowcount or 0)
