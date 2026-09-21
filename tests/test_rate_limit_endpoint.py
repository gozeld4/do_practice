from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.clock import FakeClock
from app.main import app, get_rate_limiter
from app.ratelimit import TokenBucket


def payload(user_id: str | None = None) -> dict[str, object]:
    return {
        "tenant_id": "acme",
        "user_id": user_id or f"rate-limit-test-{uuid4()}",
        "type": "training",
        "resources": {"accelerator_type": "a100", "accelerators_per_task": 1},
        "priority_class": "normal",
        "input_ref": "input",
        "output_ref": "output",
        "checkpointable": False,
        "replicas": 1,
    }


def test_denied_job_submission_returns_retry_after() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    limiter = TokenBucket(clock, rate=1, burst=0)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    try:
        response = TestClient(app).post(
            "/v1/jobs",
            json=payload(),
            headers={"Idempotency-Key": str(uuid4())},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"]["code"] == "rate_limited"


def test_thirty_requests_limit_one_user_but_not_user_b() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    limiter = TokenBucket(clock)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    try:
        responses = []
        for _ in range(30):
            responses.append(
                TestClient(app).post(
                    "/v1/jobs",
                    json=payload("user-a"),
                    headers={"Idempotency-Key": str(uuid4())},
                )
            )
        user_b = TestClient(app).post(
            "/v1/jobs",
            json=payload("user-b"),
            headers={"Idempotency-Key": str(uuid4())},
        )
    finally:
        app.dependency_overrides.clear()

    denied = [response for response in responses if response.status_code == 429]
    assert len(denied) == 20
    assert all(int(response.headers["Retry-After"]) >= 1 for response in denied)
    assert user_b.status_code == 201