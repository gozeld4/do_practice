from collections.abc import Mapping
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from app.config import Settings


class Resources(BaseModel):
    accelerator_type: str
    accelerators_per_task: int = Field(ge=1)


class JobCreate(BaseModel):
    tenant_id: str
    user_id: str
    type: Literal["training", "batch_inference"]
    resources: Resources
    priority_class: Literal["low", "normal", "high"]
    input_ref: str
    output_ref: str
    checkpointable: bool
    replicas: int | None = None
    shards: int | None = None


class ValidationError(NamedTuple):
    code: str
    message: str
    field: str


def validate(job: JobCreate | Mapping[str, object], settings: Settings) -> list[ValidationError]:
    payload = job.model_dump() if isinstance(job, JobCreate) else job
    resources = payload.get("resources", {})
    resources = resources if isinstance(resources, Mapping) else {}
    tenant_id = payload.get("tenant_id")
    accelerator_type = resources.get("accelerator_type")
    accelerators_per_task = resources.get("accelerators_per_task")
    job_type = payload.get("type")
    replicas = payload.get("replicas")
    shards = payload.get("shards")

    errors: list[ValidationError] = []
    tenant_known = tenant_id in settings.tenant_quotas

    if not tenant_known:
        errors.append(
            ValidationError(
                "unknown_tenant",
                f"unknown tenant: {tenant_id}",
                "tenant_id",
            )
        )

    if accelerator_type not in settings.accelerator_types:
        errors.append(
            ValidationError(
                "unknown_accelerator_type",
                f"unknown accelerator type: {accelerator_type}",
                "resources.accelerator_type",
            )
        )

    demand: int | None = None
    if job_type == "training":
        if not isinstance(replicas, int) or replicas < 1:
            errors.append(
                ValidationError(
                    "invalid_replicas",
                    "training jobs require replicas >= 1",
                    "replicas",
                )
            )
        else:
            demand = accelerators_per_task * replicas if isinstance(accelerators_per_task, int) else None
        if shards is not None:
            errors.append(
                ValidationError(
                    "unexpected_shards",
                    "training jobs must not set shards",
                    "shards",
                )
            )
    elif job_type == "batch_inference":
        if not isinstance(shards, int) or shards < 1:
            errors.append(
                ValidationError(
                    "invalid_shards",
                    "batch inference jobs require shards >= 1",
                    "shards",
                )
            )
        else:
            demand = accelerators_per_task if isinstance(accelerators_per_task, int) else None
        if replicas is not None:
            errors.append(
                ValidationError(
                    "unexpected_replicas",
                    "batch inference jobs must not set replicas",
                    "replicas",
                )
            )

    if tenant_known and demand is not None and demand > settings.tenant_quotas[tenant_id]:
        errors.append(
            ValidationError(
                "quota_exceeded",
                f"requested {demand} accelerators exceeds tenant quota of {settings.tenant_quotas[tenant_id]}",
                "resources.accelerators_per_task",
            )
        )

    return errors