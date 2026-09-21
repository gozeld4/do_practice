from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    index: int
    state: str
    attempt: int
    node_id: str | None
    checkpoint_ref: str | None
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