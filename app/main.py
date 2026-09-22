import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.clock import Clock, get_clock
from app.config import get_settings
from app.domain.loop import run_one_tick
from app.domain.schemas import AssignmentOut, JobOut, NodeOut, NodeUpsert
from app.domain.states import IllegalTransition, transition, transition_task
from app.domain.validation import JobCreate, validate
from app.errors import (
    AppError,
    app_error_handler,
    error_response,
    http_error_handler,
    illegal_transition_handler,
    unhandled_exception_handler,
)
from app.idempotency import request_hash
from app.ratelimit import TokenBucket
from app.store.db import engine, get_session
from app.store.models import Job, Node, Task

logger = logging.getLogger(__name__)


async def scheduler_loop(stop_event: asyncio.Event, clock: Clock) -> None:
    settings = get_settings()
    while not stop_event.is_set():
        try:
            with Session(engine) as session:
                run_one_tick(session, clock)
        except Exception:
            logger.exception("scheduler tick failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_tick_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(stop_event, get_clock()))
    try:
        yield
    finally:
        stop_event.set()
        await task


app = FastAPI(lifespan=lifespan)
rate_limiter = TokenBucket()


def get_rate_limiter() -> TokenBucket:
    return rate_limiter


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > get_settings().max_body_bytes:
        return error_response(request, 413, "payload_too_large", "request body is too large")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(IllegalTransition, illegal_transition_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0]
    location = first_error.get("loc", ())
    field = ".".join(str(part) for part in location if part != "body") or None
    return error_response(
        request,
        422,
        "validation_error",
        first_error.get("msg", "Request validation failed"),
        field,
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "not ready"})

    return JSONResponse(status_code=200, content={"status": "ready"})


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": get_settings().app_version}


@app.post("/v1/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    job_create: JobCreate,
    limiter: Annotated[TokenBucket, Depends(get_rate_limiter)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    allowed, retry_after = limiter.try_acquire((job_create.tenant_id, job_create.user_id))
    if not allowed:
        raise AppError(429, "rate_limited", "submission rate limit exceeded", retry_after=retry_after)

    if not idempotency_key:
        raise AppError(400, "missing_idempotency_key", "Idempotency-Key header is required")

    errors = validate(job_create, get_settings())
    if errors:
        error = errors[0]
        raise AppError(422, error.code, error.message, error.field)

    body_hash = request_hash(job_create)
    existing = session.scalar(
        select(Job)
        .options(selectinload(Job.tasks))
        .where(Job.tenant_id == job_create.tenant_id, Job.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.request_hash != body_hash:
            raise AppError(422, "idempotency_key_conflict", "Idempotency-Key was used with a different request")
        response.status_code = status.HTTP_200_OK
        return existing

    session.rollback()
    pending_count = session.scalar(
        select(func.count()).select_from(Job).where(
            Job.tenant_id == job_create.tenant_id,
            Job.state == "PENDING",
        )
    )
    if pending_count >= get_settings().max_pending_per_tenant:
        raise AppError(
            429,
            "too_many_pending",
            f"tenant {job_create.tenant_id} has reached its pending job limit",
            "tenant_id",
        )
    session.rollback()

    job_data = job_create.model_dump()
    resources = job_data.pop("resources")
    task_count = job_data["replicas"] if job_data["type"] == "training" else job_data["shards"]
    job_data["replicas"] = job_data["replicas"] or 1
    job_data["shards"] = job_data["shards"] or 1
    job = Job(
        **job_data,
        accelerator_type=resources["accelerator_type"],
        accelerators_per_task=resources["accelerators_per_task"],
        idempotency_key=idempotency_key,
        request_hash=body_hash,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    try:
        with session.begin():
            session.add(job)
            session.flush()
            job.tasks = [Task(job_id=job.id, index=index) for index in range(task_count)]
            session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Job)
            .options(selectinload(Job.tasks))
            .where(Job.tenant_id == job_create.tenant_id, Job.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        if existing.request_hash != body_hash:
            raise AppError(422, "idempotency_key_conflict", "Idempotency-Key was used with a different request")
        response.status_code = status.HTTP_200_OK
        return existing
    return job


@app.get("/v1/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, session: Annotated[Session, Depends(get_session)]) -> Job:
    job = session.scalar(select(Job).options(selectinload(Job.tasks)).where(Job.id == job_id))
    if job is None:
        raise AppError(404, "job_not_found", f"job {job_id} not found")
    return job


@app.get("/v1/jobs", response_model=list[JobOut])
def list_jobs(
    session: Annotated[Session, Depends(get_session)],
    tenant: str | None = None,
    user: str | None = None,
    state: str | None = None,
) -> list[Job]:
    query = select(Job).options(selectinload(Job.tasks)).order_by(Job.created_at.desc()).limit(100)
    if tenant is not None:
        query = query.where(Job.tenant_id == tenant)
    if user is not None:
        query = query.where(Job.user_id == user)
    if state is not None:
        query = query.where(Job.state == state)
    return list(session.scalars(query).unique().all())


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: UUID, session: Annotated[Session, Depends(get_session)]) -> Job:
    with session.begin():
        job = session.scalar(select(Job).options(selectinload(Job.tasks)).where(Job.id == job_id))
        if job is None:
            raise AppError(404, "job_not_found", f"job {job_id} not found")
        job.state = transition(job.state, "CANCELLED")
        for task in job.tasks:
            if task.state in {"PENDING", "LEASED"}:
                task.state = transition_task(task.state, "FAILED")
        session.flush()
    return job


@app.put("/v1/nodes/{node_id}", response_model=NodeOut)
def upsert_node(
    node_id: str,
    node_upsert: NodeUpsert,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    response: Response,
) -> Node:
    if node_upsert.accelerator_type not in get_settings().accelerator_types:
        raise AppError(
            422,
            "unknown_accelerator_type",
            f"unknown accelerator type: {node_upsert.accelerator_type}",
            "accelerator_type",
        )

    node = session.get(Node, node_id)
    now = clock.now()
    if node is None:
        node = Node(id=node_id, **node_upsert.model_dump(), last_seen=now)
        response.status_code = status.HTTP_201_CREATED
    else:
        node.pool = node_upsert.pool
        node.accelerator_type = node_upsert.accelerator_type
        node.capacity = node_upsert.capacity
        node.last_seen = now

    session.add(node)
    session.commit()
    return node


@app.get("/v1/nodes/{node_id}/assignments", response_model=list[AssignmentOut])
def node_assignments(
    node_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[AssignmentOut]:
    if session.get(Node, node_id) is None:
        raise AppError(404, "node_not_found", f"node {node_id} not found")

    tasks = session.scalars(
        select(Task).where(Task.node_id == node_id, Task.state == "LEASED").order_by(Task.index)
    ).all()
    return [
        {
            "task_id": task.id,
            "job_id": task.job_id,
            "lease_id": task.lease_id,
            "epoch": task.epoch,
            "expires_at": task.expires_at,
            "checkpoint_ref": task.checkpoint_ref,
        }
        for task in tasks
    ]