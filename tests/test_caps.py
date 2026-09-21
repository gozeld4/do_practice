from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

client = TestClient(app)


def payload() -> dict[str, object]:
    return {
        "tenant_id": "acme",
        "user_id": f"caps-test-{uuid4()}",
        "type": "training",
        "resources": {"accelerator_type": "a100", "accelerators_per_task": 1},
        "priority_class": "normal",
        "input_ref": "input",
        "output_ref": "output",
        "checkpointable": False,
        "replicas": 1,
    }


def test_body_over_64_kib_is_rejected_before_parsing() -> None:
    response = client.post(
        "/v1/jobs",
        content=b"{" + b" " * (64 * 1024) + b"}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_pending_job_cap_returns_429(monkeypatch) -> None:
    import app.main as main_module

    settings = Settings(max_pending_per_tenant=1)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    first = client.post("/v1/jobs", json=payload(), headers={"Idempotency-Key": str(uuid4())})
    second = client.post("/v1/jobs", json=payload(), headers={"Idempotency-Key": str(uuid4())})

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "too_many_pending"