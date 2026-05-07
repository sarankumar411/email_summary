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
        """Create a job row in the DB and dispatch a Celery task for it; return the new Job.

        Logic:
            1. INSERT a job row with status='queued' and expires_at = now() + 24 h.
            2. COMMIT — the commit happens before Celery dispatch so the worker can load
               the job row immediately when it picks up the task.
            3. Fire-and-forget the Celery task via .delay(), passing job_id, client_id,
               triggered_by_accountant_id, and the force flag as JSON-safe strings.
            4. Return the Job so the router can build a 202 response with the job_id.

        Dry run:
            client_id=UUID("cli-1"), triggered_by.id=UUID("acc-1"), force=False
            → Job(id=UUID("job-1"), status=JobStatus.queued)
            → Celery task queued: refresh_summary_task.delay("job-1", "cli-1", "acc-1", False)
        """
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
        """Return the Job if the caller is authorised to see it; raise NotFoundError otherwise.

        Visibility rules (enumeration-resistant — all denials raise NotFoundError):
            - superuser     : always visible.
            - requester     : the accountant who triggered the job can always see their own.
            - admin         : visible when the job's client or requester belongs to the admin's firm.
            - anyone else   : 404.

        The admin path calls _job_belongs_to_firm which makes up to 2 extra DB lookups
        (client → firm, requester → firm); acceptable given jobs are polled infrequently.

        Dry run (requester reads their own job):
            job.triggered_by_accountant_id == current_user.id → returns Job.
        Dry run (admin, job belongs to same-firm client):
            → returns Job.
        Dry run (admin, job belongs to different firm):
            → raises NotFoundError("Job not found")
        """
        job = await self.repository.get_job(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        if current_user.role == "superuser" or job.triggered_by_accountant_id == current_user.id:
            return job
        if current_user.role == "admin" and await self._job_belongs_to_firm(job, current_user.firm_id):
            return job
        raise NotFoundError("Job not found")

    async def mark_running(self, job_id: uuid.UUID) -> None:
        """Transition job status to 'running' and stamp started_at. Called by the Celery task on pickup."""
        await self.repository.set_running(job_id)

    async def mark_completed(
        self,
        job_id: uuid.UUID,
        *,
        status: CompletionStatus,
        result: dict,
        error_message: str | None = None,
    ) -> None:
        """Transition job to a terminal state (completed / failed / skipped).

        Maps the string literal status to the JobStatus enum and delegates to the repository.
        result is stored as JSONB and is the payload returned by GET /jobs/{id}.

        Dry run (success):
            status="completed", result={"status":"completed","emails_analyzed_count":15}
            → job.status=JobStatus.completed, job.completed_at=now().
        Dry run (failure):
            status="failed", error_message="gemini unavailable"
            → job.status=JobStatus.failed, job.error_message="gemini unavailable".
        """
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
        """Hard-delete expired job rows and commit. Returns the number of rows deleted.

        Called hourly by the Celery beat schedule (cleanup_expired_jobs_task).
        Jobs have a 24-hour TTL set at creation (expires_at = created_at + job_ttl_hours).

        Dry run: 5 jobs expired → deletes them, returns 5.
        Dry run: nothing expired → returns 0.
        """
        deleted = await self.repository.delete_expired()
        await self.session.commit()
        return deleted

    async def _job_belongs_to_firm(self, job: Job, firm_id: uuid.UUID) -> bool:
        """Return True if the job's client or the job's requester belongs to the given firm.

        Used by get_visible_job to decide admin visibility. Checks the client first (faster
        path for refresh jobs which always have a client_id). Falls back to checking the
        requester's firm if the client lookup does not match or job has no client_id.

        Dry run (refresh job, client.firm_id == firm_id):
            → True  (stops after client check)
        Dry run (client.firm_id != firm_id, requester.firm_id == firm_id):
            → True  (falls through to requester check)
        Dry run (both belong to different firms):
            → False
        """
        if job.client_id is not None:
            client = await self.clients_service.get_client_context(job.client_id)
            if client is not None and client.firm_id == firm_id:
                return True

        requester = await self.identity_service.get_accountant_context(job.triggered_by_accountant_id)
        return requester is not None and requester.firm_id == firm_id
