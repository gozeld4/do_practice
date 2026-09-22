from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clock import FakeClock
from app.domain.loop import run_one_tick
from app.store.db import engine
from app.store.models import Job, Node, Task


def test_run_one_tick_places_pending_task() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        job = Job(
            tenant_id="acme",
            user_id="loop-test",
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
            state="PENDING",
        )
        session.add(job)
        session.flush()
        task = Task(job_id=job.id, index=0)
        session.add_all([task, Node(id="node-loop", pool="east", accelerator_type="a100", capacity=2)])
        session.commit()

        run_one_tick(session, FakeClock(start))
        session.refresh(task)
        session.refresh(job)

        assert task.state == "LEASED"
        assert task.node_id == "node-loop"
        assert job.state == "RUNNING"