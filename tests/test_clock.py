from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.clock import FakeClock, get_clock
from app.main import app


def test_fake_clock_can_advance_without_sleeping() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(start)

    clock.advance(31)

    assert clock.now() == datetime(2026, 1, 1, 0, 0, 31, tzinfo=UTC)


def test_create_job_uses_overridden_clock() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    app.dependency_overrides[get_clock] = lambda: clock
    payload = {
        "tenant_id": "acme",
        "user_id": f"clock-test-{uuid4()}",
        "type": "training",
        "resources": {"accelerator_type": "a100", "accelerators_per_task": 1},
        "priority_class": "normal",
        "input_ref": "input",
        "output_ref": "output",
        "checkpointable": False,
        "replicas": 1,
    }

    try:
        response = TestClient(app).post(
            "/v1/jobs", json=payload, headers={"Idempotency-Key": str(uuid4())}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["created_at"] == "2026-01-01T00:00:00Z"