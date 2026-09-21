from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.clock import current_time


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("type IN ('training', 'batch_inference')", name="ck_jobs_type"),
        CheckConstraint("accelerators_per_task > 0", name="ck_jobs_accelerators_per_task_positive"),
        CheckConstraint("priority_class IN ('low', 'normal', 'high')", name="ck_jobs_priority_class"),
        CheckConstraint("replicas > 0", name="ck_jobs_replicas_positive"),
        CheckConstraint("shards > 0", name="ck_jobs_shards_positive"),
        CheckConstraint("state IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')", name="ck_jobs_state"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_id_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    accelerator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    accelerators_per_task: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_class: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    input_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    output_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    checkpointable: Mapped[bool] = mapped_column(nullable=False, default=False)
    replicas: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    shards: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    pending_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=current_time)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=current_time, onupdate=current_time
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("job_id", "index", name="uq_tasks_job_id_index"),
        CheckConstraint("state IN ('PENDING', 'LEASED', 'COMMITTED', 'FAILED')", name="ck_tasks_state"),
        CheckConstraint("attempt >= 0", name="ck_tasks_attempt_nonnegative"),
        CheckConstraint('"index" >= 0', name="ck_tasks_index_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_id: Mapped[str | None] = mapped_column(String(255))
    checkpoint_ref: Mapped[str | None] = mapped_column(String(2048))
    output_ref: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=current_time)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=current_time, onupdate=current_time
    )
    job: Mapped[Job] = relationship(back_populates="tasks")