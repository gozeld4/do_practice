from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.snapshot import load_snapshot
from app.store.db import engine
from app.store.models import Job, Node, Task


def make_job(session: Session, tenant_id: str, state: str, created_at: datetime) -> Job:
    job = Job(
        tenant_id=tenant_id,
        user_id="snapshot-test",
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
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(job)
    session.flush()
    return job


def test_load_snapshot_queries_pending_nodes_and_usage() -> None:
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    second_time = datetime(2026, 1, 2, tzinfo=UTC)
    with Session(engine) as session:
        first_job = make_job(session, "acme", "PENDING", first_time)
        second_job = make_job(session, "globex", "RUNNING", second_time)
        finished_job = make_job(session, "acme", "SUCCEEDED", first_time)
        session.add_all(
            [
                Task(job_id=first_job.id, index=0, state="PENDING"),
                    Task(job_id=second_job.id, index=0, state="PENDING"),
                    Task(job_id=second_job.id, index=1, state="LEASED", node_id="node-a"),
                Task(job_id=finished_job.id, index=0, state="LEASED", node_id="node-b"),
                Node(id="node-a", pool="east", accelerator_type="a100", capacity=8, last_seen=second_time),
                Node(id="node-b", pool="west", accelerator_type="h100", capacity=4, last_seen=second_time),
            ]
        )
        session.flush()

        pending, nodes, usage = load_snapshot(session)

    assert [(item.job_id, item.tenant_id) for item in pending] == [(str(first_job.id), "acme"), (str(second_job.id), "globex")]
    assert [(item.node_id, item.accelerator_type, item.free) for item in nodes] == [
        ("node-a", "a100", 6),
        ("node-b", "h100", 2),
    ]
    assert usage == {"globex": 2, "acme": 2}