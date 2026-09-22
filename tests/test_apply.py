from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clock import FakeClock
from app.config import Settings
from app.domain.apply import apply
from app.domain.scheduling import Placement, ScheduleResult
from app.store.db import engine
from app.store.models import Job, Task


def make_job(session: Session, state: str = "PENDING", pending_reason: str | None = "capacity") -> Job:
    job = Job(
        tenant_id="acme",
        user_id="apply-test",
        idempotency_key=str(uuid4()),
        request_hash="hash",
        type="training",
        accelerator_type="a100",
        accelerators_per_task=2,
        input_ref="input",
        output_ref="output",
        checkpointable=False,
        replicas=1,
        shards=1,
        state=state,
        pending_reason=pending_reason,
    )
    session.add(job)
    session.flush()
    return job


def test_apply_leases_tasks_and_marks_jobs_running() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(start)
    with Session(engine) as session:
        job = make_job(session)
        task = Task(job_id=job.id, index=0, epoch=2)
        session.add(task)
        session.commit()

        apply(
            session,
            ScheduleResult([Placement(str(task.id), "node-a")], {}),
            clock,
            Settings(lease_ttl_seconds=30),
        )
        session.refresh(task)
        session.refresh(job)

        assert task.state == "LEASED"
        assert task.node_id == "node-a"
        assert task.lease_id is not None
        assert task.epoch == 3
        assert task.expires_at == start + timedelta(seconds=30)
        assert job.state == "RUNNING"
        assert job.pending_reason is None


def test_apply_records_unplaced_reason() -> None:
    with Session(engine) as session:
        job = make_job(session)
        session.commit()

        apply(
            session,
            ScheduleResult([], {str(job.id): "quota"}),
            FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
            Settings(),
        )
        session.refresh(job)

        assert job.pending_reason == "quota"