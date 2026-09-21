import pytest
from pydantic import ValidationError as PydanticValidationError

from app.config import Settings
from app.domain.validation import JobCreate, validate

SETTINGS = Settings()


def job(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": "acme",
        "user_id": "user-1",
        "type": "training",
        "resources": {"accelerator_type": "a100", "accelerators_per_task": 2},
        "priority_class": "normal",
        "input_ref": "input",
        "output_ref": "output",
        "checkpointable": False,
        "replicas": 2,
        "shards": None,
    }
    value.update(overrides)
    return value


def error_codes(value: dict[str, object]) -> list[str]:
    return [error.code for error in validate(value, SETTINGS)]


def test_valid_training_job_has_no_errors() -> None:
    assert validate(job(), SETTINGS) == []


def test_unknown_tenant_is_rejected() -> None:
    errors = validate(job(tenant_id="unknown"), SETTINGS)

    assert [(error.code, error.field) for error in errors] == [("unknown_tenant", "tenant_id")]


def test_unknown_accelerator_type_is_rejected() -> None:
    errors = validate(job(resources={"accelerator_type": "v100", "accelerators_per_task": 2}), SETTINGS)

    assert [(error.code, error.field) for error in errors] == [
        ("unknown_accelerator_type", "resources.accelerator_type")
    ]


def test_batch_job_cannot_set_replicas() -> None:
    assert error_codes(job(type="batch_inference", replicas=1, shards=2)) == ["unexpected_replicas"]


def test_training_job_cannot_set_shards() -> None:
    assert error_codes(job(shards=1)) == ["unexpected_shards"]


def test_batch_job_requires_shards() -> None:
    assert error_codes(job(type="batch_inference", replicas=None, shards=None)) == ["invalid_shards"]


def test_training_job_requires_replicas() -> None:
    assert error_codes(job(replicas=None, shards=None)) == ["invalid_replicas"]


def test_training_demand_must_fit_quota() -> None:
    errors = validate(job(replicas=9), SETTINGS)

    assert [(error.code, error.field) for error in errors] == [
        ("quota_exceeded", "resources.accelerators_per_task")
    ]


def test_batch_quota_is_based_on_one_shard() -> None:
    assert validate(job(type="batch_inference", replicas=None, shards=100), SETTINGS) == []


def test_pydantic_owns_shape_validation() -> None:
    with pytest.raises(PydanticValidationError):
        JobCreate(**job(resources={"accelerator_type": "a100", "accelerators_per_task": 0}))

    with pytest.raises(PydanticValidationError):
        JobCreate(**job(type="unsupported"))