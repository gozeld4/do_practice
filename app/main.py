from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.domain.schemas import JobOut
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
from app.store.db import get_session
from app.store.models import Job, Task

app = FastAPI()


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
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
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    if not idempotency_key:
        raise AppError(400, "missing_idempotency_key", "Idempotency-Key header is required")

    errors = validate(job_create, get_settings())
    if errors:
        error = errors[0]
        raise AppError(422, error.code, error.message, error.field)

    job_data = job_create.model_dump()
    resources = job_data.pop("resources")
    task_count = job_data["replicas"] if job_data["type"] == "training" else job_data["shards"]
    job = Job(
        **job_data,
        accelerator_type=resources["accelerator_type"],
        accelerators_per_task=resources["accelerators_per_task"],
    )
    with session.begin():
        session.add(job)
        session.flush()
        job.tasks = [Task(job_id=job.id, index=index) for index in range(task_count)]
        session.flush()
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