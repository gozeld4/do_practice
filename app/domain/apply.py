from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.domain.rollup import rollup
from app.domain.scheduling import ScheduleResult
from app.domain.states import transition, transition_task
from app.store.models import Job, Task


def apply(session: Session, result: ScheduleResult, clock: Clock, settings: Settings) -> None:
    now = clock.now()
    expires_at = now + timedelta(seconds=settings.lease_ttl_seconds)

    session.rollback()
    with session.begin():
        for placement in result.placements:
            task = session.get(Task, UUID(placement.task_id))
            if task is None:
                raise ValueError(f"task {placement.task_id} not found")

            task.state = transition_task(task.state, "LEASED")
            task.node_id = placement.node_id
            task.lease_id = str(uuid4())
            task.epoch += 1
            task.expires_at = expires_at
            rollup(session, task.job_id)

            job = task.job
            if job.state != "RUNNING":
                job.state = transition(job.state, "RUNNING")
            job.pending_reason = None

        for job_id, reason in result.unplaced.items():
            job = session.get(Job, UUID(job_id))
            if job is None:
                raise ValueError(f"job {job_id} not found")
            job.pending_reason = reason