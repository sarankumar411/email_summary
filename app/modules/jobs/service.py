import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth_context import AuthenticatedUser
from app.core.exceptions import NotFoundError
from app.modules.clients.service import ClientsService
from app.modules.identity.service import IdentityService
from app.modules.jobs.models import Job, JobStatus
from app.modules.jobs.repository import JobsRepository

CompletionStatus = Literal["completed", "failed", "skipped"]


class JobsService:
    """Create and read async jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = JobsRepository(session)
        self.settings = get_settings()
        self.clients_service = ClientsService(session)
        self.identity_service = IdentityService(session)

    async def enqueue_refresh(
        self,
        *,
        client_id: uuid.UUID,
        triggered_by: AuthenticatedUser,
        force: bool,
    ) -> Job:
        job = await self.repository.create_refresh_job(
            client_id=client_id,
            triggered_by_accountant_id=triggered_by.id,
            expires_at=datetime.now(UTC) + timedelta(hours=self.settings.job_ttl_hours),
        )
        await self.session.commit()

        from app.modules.summarization.tasks import refresh_summary_task

        refresh_summary_task.delay(str(job.id), str(client_id), str(triggered_by.id), force)
        return job

    async def get_visible_job(self, job_id: uuid.UUID, current_user: AuthenticatedUser) -> Job:
        job = await self.repository.get_job(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        if current_user.role == "superuser" or job.triggered_by_accountant_id == current_user.id:
            return job
        if current_user.role == "admin" and await self._job_belongs_to_firm(job, current_user.firm_id):
            return job
        raise NotFoundError("Job not found")

    async def mark_running(self, job_id: uuid.UUID) -> None:
        """Mark a background job as running."""

        await self.repository.set_running(job_id)

    async def mark_completed(
        self,
        job_id: uuid.UUID,
        *,
        status: CompletionStatus,
        result: dict,
        error_message: str | None = None,
    ) -> None:
        """Mark a background job as completed, failed, or skipped."""

        status_map = {
            "completed": JobStatus.completed,
            "failed": JobStatus.failed,
            "skipped": JobStatus.skipped,
        }
        await self.repository.set_completed(
            job_id,
            status=status_map[status],
            result=result,
            error_message=error_message,
        )

    async def cleanup_expired_jobs(self) -> int:
        deleted = await self.repository.delete_expired()
        await self.session.commit()
        return deleted

    async def _job_belongs_to_firm(self, job: Job, firm_id: uuid.UUID) -> bool:
        if job.client_id is not None:
            client = await self.clients_service.get_client_context(job.client_id)
            if client is not None and client.firm_id == firm_id:
                return True

        requester = await self.identity_service.get_accountant_context(job.triggered_by_accountant_id)
        return requester is not None and requester.firm_id == firm_id
