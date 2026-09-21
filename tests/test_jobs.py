from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def payload(user_id: str | None = None) -> dict[str, object]:
    return {
        "tenant_id": "acme",
        "user_id": user_id or f"endpoint-test-{uuid4()}",
        "type": "training",
        "resources": {"accelerator_type": "a100", "accelerators_per_task": 2},
        "priority_class": "normal",
        "input_ref": "input",
        "output_ref": "output",
        "checkpointable": False,
        "replicas": 2,
    }


def headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


def test_valid_job_returns_201_and_pending() -> None:
    response = client.post("/v1/jobs", json=payload(), headers=headers())

    assert response.status_code == 201
    assert response.json()["state"] == "PENDING"


def test_replicas_four_creates_four_tasks() -> None:
    body = payload()
    body["replicas"] = 4

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 201
    assert len(response.json()["tasks"]) == 4


def test_get_and_list_job_return_created_job() -> None:
    user_id = f"list-test-{uuid4()}"
    created = client.post("/v1/jobs", json=payload(user_id), headers=headers())
    job_id = created.json()["id"]

    fetched = client.get(f"/v1/jobs/{job_id}")
    listed = client.get(f"/v1/jobs?tenant=acme&user={user_id}")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == job_id
    assert [item["id"] for item in listed.json()] == [job_id]


def test_unknown_tenant_is_rejected_with_envelope() -> None:
    body = payload()
    body["tenant_id"] = "unknown"

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_tenant"
    assert response.json()["error"]["field"] == "tenant_id"


def test_unknown_accelerator_type_is_rejected_with_envelope() -> None:
    body = payload()
    body["resources"] = {"accelerator_type": "v100", "accelerators_per_task": 2}

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_accelerator_type"
    assert response.json()["error"]["field"] == "resources.accelerator_type"


def test_zero_accelerators_per_task_is_rejected_with_envelope() -> None:
    body = payload()
    body["resources"] = {"accelerator_type": "a100", "accelerators_per_task": 0}

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["field"] == "resources.accelerators_per_task"


def test_replicas_on_batch_job_is_rejected_with_envelope() -> None:
    body = payload()
    body["type"] = "batch_inference"
    body["shards"] = 2

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unexpected_replicas"
    assert response.json()["error"]["field"] == "replicas"


def test_shards_on_training_job_is_rejected_with_envelope() -> None:
    body = payload()
    body["shards"] = 2

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unexpected_shards"
    assert response.json()["error"]["field"] == "shards"


def test_oversized_job_is_rejected_with_quota_reason() -> None:
    body = payload()
    body["replicas"] = 9

    response = client.post("/v1/jobs", json=body, headers=headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quota_exceeded"


def test_unknown_id_returns_404_envelope() -> None:
    response = client.get(f"/v1/jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_cancelling_twice_returns_illegal_transition() -> None:
    created = client.post("/v1/jobs", json=payload(), headers=headers())
    job_id = created.json()["id"]

    assert client.post(f"/v1/jobs/{job_id}/cancel").status_code == 200
    response = client.post(f"/v1/jobs/{job_id}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "illegal_transition"


def test_missing_idempotency_header_returns_400() -> None:
    response = client.post("/v1/jobs", json=payload())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_idempotency_key"
