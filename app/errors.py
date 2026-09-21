import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.states import IllegalTransition

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        field: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.retry_after = retry_after


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    field: str | None = None,
    retry_after: float | None = None,
) -> JSONResponse:
    request_id = request.state.request_id
    headers = {"X-Request-ID": request_id}
    if retry_after is not None:
        headers["Retry-After"] = str(int(retry_after))
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "field": field,
                "request_id": request_id,
            }
        },
        headers=headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc.status, exc.code, exc.message, exc.field, exc.retry_after)


async def illegal_transition_handler(request: Request, exc: IllegalTransition) -> JSONResponse:
    return error_response(request, 409, "illegal_transition", str(exc))


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = exc.status_code
    code = "not_found" if status == 404 else "http_error"
    return error_response(request, status, code, str(exc.detail))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.state.request_id
    logger.exception("Unhandled exception request_id=%s", request_id, exc_info=exc)
    return error_response(request, 500, "internal_error", "internal error")