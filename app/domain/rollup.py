from collections import Counter
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.states import transition
from app.store.models import Job, Task


def rollup(session: Session, job_id: UUID) -> None:
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")

    counts = Counter(
        dict(
            session.execute(
                select(Task.state, func.count()).where(Task.job_id == job_id).group_by(Task.state)
            ).all()
        )
    )
    total_count = sum(counts.values())
    committed_count = counts["COMMITTED"]

    if counts["FAILED"] > 0 and job.state not in {"FAILED", "SUCCEEDED", "CANCELLED"}:
        job.state = transition(job.state, "FAILED")
    elif total_count > 0 and committed_count == total_count and job.state not in {"SUCCEEDED", "CANCELLED"}:
        job.state = transition(job.state, "SUCCEEDED")
