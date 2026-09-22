from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    index: int
    state: str
    attempt: int
    node_id: str | None
    checkpoint_ref: str | None
    error: str | None
    output_ref: str | None
    created_at: datetime
    updated_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    user_id: str
    type: str
    accelerator_type: str
    accelerators_per_task: int
    priority_class: str
    input_ref: str
    output_ref: str
    checkpointable: bool
    replicas: int
    shards: int
    state: str
    pending_reason: str | None
    created_at: datetime
    updated_at: datetime
    tasks: list[TaskOut]


class NodeUpsert(BaseModel):
    pool: str
    accelerator_type: str
    capacity: int = Field(ge=1)


class NodeOut(NodeUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    last_seen: datetime


class AssignmentOut(BaseModel):
    task_id: UUID
    job_id: UUID
    lease_id: str | None
    epoch: int
    expires_at: datetime | None
    checkpoint_ref: str | None


class HeartbeatIn(BaseModel):
    epoch: int = Field(ge=0)
    checkpoint_ref: str | None = None


class CompleteIn(BaseModel):
    epoch: int = Field(ge=0)
    status: Literal["succeeded", "failed"]
    output_ref: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "CompleteIn":
        if self.status == "succeeded" and not self.output_ref:
            raise ValueError("output_ref is required when status is succeeded")
        if self.status == "failed" and not self.error:
            raise ValueError("error is required when status is failed")
        return self