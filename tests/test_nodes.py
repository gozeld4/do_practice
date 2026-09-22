from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.clock import FakeClock, get_clock
from app.main import app

client = TestClient(app)


def test_put_node_creates_then_updates_one_row() -> None:
    node_id = f"node-{uuid4()}"
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    app.dependency_overrides[get_clock] = lambda: clock

    try:
        created = client.put(
            f"/v1/nodes/{node_id}",
            json={"pool": "east", "accelerator_type": "a100", "capacity": 4},
        )
        first_seen = created.json()["last_seen"]
        clock.advance(1)
        updated = client.put(
            f"/v1/nodes/{node_id}",
            json={"pool": "west", "accelerator_type": "a100", "capacity": 8},
        )
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["id"] == node_id
    assert updated.json()["pool"] == "west"
    assert updated.json()["capacity"] == 8
    assert updated.json()["last_seen"] > first_seen


def test_put_node_rejects_unknown_accelerator() -> None:
    response = client.put(
        f"/v1/nodes/node-{uuid4()}",
        json={"pool": "east", "accelerator_type": "v100", "capacity": 4},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_accelerator_type"


def test_put_node_rejects_non_positive_capacity() -> None:
    response = client.put(
        f"/v1/nodes/node-{uuid4()}",
        json={"pool": "east", "accelerator_type": "a100", "capacity": 0},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["field"] == "capacity"