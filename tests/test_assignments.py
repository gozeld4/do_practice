from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.store.db import engine
from app.store.models import Job, Node, Task

client = TestClient(app)


def test_assignments_returns_only_leased_tasks_for_known_node() -> None:
    node_id = f"node-{uuid4()}"
    with Session(engine) as session:
        job = Job(
            tenant_id="acme",
            user_id="assignment-test",
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
        session.add_all([Node(id=node_id, pool="east", accelerator_type="a100", capacity=2), job])
        session.flush()
        leased = Task(
            job_id=job.id,
            index=0,
            node_id=node_id,
            state="LEASED",
            lease_id="lease-1",
            epoch=2,
            expires_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=30),
            checkpoint_ref="checkpoint-1",
        )
        session.add_all([leased, Task(job_id=job.id, index=1, node_id=node_id, state="PENDING")])
        session.flush()
        leased_id = leased.id
        job_id = job.id
        session.commit()

    response = client.get(f"/v1/nodes/{node_id}/assignments")

    assert response.status_code == 200
    assert response.json() == [
        {
            "task_id": str(leased_id),
            "job_id": str(job_id),
            "lease_id": "lease-1",
            "epoch": 2,
            "expires_at": "2026-01-01T00:00:30Z",
            "checkpoint_ref": "checkpoint-1",
        }
    ]


def test_assignments_unknown_node_returns_404() -> None:
    response = client.get(f"/v1/nodes/{uuid4()}/assignments")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "node_not_found"