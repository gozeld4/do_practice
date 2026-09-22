from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clock import FakeClock
from app.store.db import engine
from app.store.lease import update_if_current
from app.store.models import Job, Task


def seed_task(session: Session, expires_at: datetime, state: str = "LEASED", epoch: int = 1) -> Task:
    job = Job(
        tenant_id="acme",
        user_id="lease-test",
        idempotency_key=str(uuid4()),
        request_hash="hash",
        type="training",
        accelerator_type="a100",
        accelerators_per_task=1,
        input_ref="input",
        output_ref="output",
        checkpointable=False,
        replicas=1,
        shards=1,
        state="RUNNING",
    )
    session.add(job)
    session.flush()
    task = Task(
        job_id=job.id,
        index=0,
        state=state,
        lease_id="lease-1",
        epoch=epoch,
        expires_at=expires_at,
    )
    session.add(task)
    session.commit()
    return task


def test_update_if_current_updates_current_lease() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        task = seed_task(session, now + timedelta(seconds=30))

        assert update_if_current(session, "lease-1", 1, now, checkpoint_ref="checkpoint-1")
        session.commit()
        session.refresh(task)

        assert task.checkpoint_ref == "checkpoint-1"


def test_update_if_current_rejects_expired_lease() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    with Session(engine) as session:
        task = seed_task(session, clock.now() + timedelta(seconds=30))
        clock.advance(31)

        assert not update_if_current(session, "lease-1", 1, clock.now(), checkpoint_ref="late")
        session.rollback()
        session.refresh(task)

        assert task.checkpoint_ref is None


def test_update_if_current_rejects_wrong_epoch() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        task = seed_task(session, now + timedelta(seconds=30), epoch=2)

        assert not update_if_current(session, "lease-1", 1, now, checkpoint_ref="stale")
        session.rollback()
        session.refresh(task)

        assert task.checkpoint_ref is None


def test_update_if_current_rejects_committed_task() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        task = seed_task(session, now + timedelta(seconds=30), state="COMMITTED")

        assert not update_if_current(session, "lease-1", 1, now, checkpoint_ref="duplicate")
        session.rollback()
        session.refresh(task)

        assert task.checkpoint_ref is None