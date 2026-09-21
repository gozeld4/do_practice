from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.validation import JobCreate
from app.idempotency import request_hash
from app.main import app

client = TestClient(app)


def payload() -> dict[str, object]:
    return {
        "tenant_id": "acme",
        "user_id": f"idempotency-test-{uuid4()}",
        "type": "training",
        "resources": {"accelerator_type": "a100", "accelerators_per_task": 1},
        "priority_class": "normal",
        "input_ref": "input",
        "output_ref": "output",
        "checkpointable": False,
        "replicas": 1,
    }


def test_same_key_and_body_returns_existing_job() -> None:
    body = payload()
    key = str(uuid4())

    first = client.post("/v1/jobs", json=body, headers={"Idempotency-Key": key})
    second = client.post("/v1/jobs", json=body, headers={"Idempotency-Key": key})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_same_key_with_different_body_returns_conflict() -> None:
    body = payload()
    key = str(uuid4())
    client.post("/v1/jobs", json=body, headers={"Idempotency-Key": key})
    body["user_id"] = "different-user"

    response = client.post("/v1/jobs", json=body, headers={"Idempotency-Key": key})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_conflict"


def test_request_hash_is_independent_of_key_order() -> None:
    first = JobCreate(**payload())
    second = JobCreate(
        checkpointable=first.checkpointable, output_ref=first.output_ref, input_ref=first.input_ref, priority_class=first.priority_class, resources=first.resources.model_dump(), type=first.type, user_id=first.user_id, tenant_id=first.tenant_id, replicas=first.replicas
    )

    assert request_hash(first) == request_hash(second)