import asyncio
import json

from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from starlette.requests import Request

from app.main import app

client = TestClient(app)


def test_unknown_route_uses_error_envelope() -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Not Found"
    assert response.json()["error"]["field"] is None
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "detail" not in response.json()


class RequestBody(BaseModel):
    accelerators_per_task: int = Field(ge=1)


def test_validation_error_uses_error_envelope() -> None:
    try:
        RequestBody(accelerators_per_task=0)
    except PydanticValidationError as error:
        validation_error = RequestValidationError(
            [
                {
                    "type": item["type"],
                    "loc": ("body", "accelerators_per_task"),
                    "msg": item["msg"],
                    "input": item.get("input"),
                }
                for item in error.errors()
            ]
        )

    scope = {"type": "http", "method": "POST", "path": "/jobs", "headers": []}
    request = Request(scope)
    request.state.request_id = "req-test"
    handler = app.exception_handlers[RequestValidationError]
    response = asyncio.run(handler(request, validation_error))

    assert response.status_code == 422
    assert json.loads(response.body) == {
        "error": {
            "code": "validation_error",
            "message": "Input should be greater than or equal to 1",
            "field": "accelerators_per_task",
            "request_id": "req-test",
        }
    }
    assert response.headers["X-Request-ID"] == "req-test"


def test_unhandled_exception_hides_details_and_logs_request_id(caplog) -> None:
    scope = {"type": "http", "method": "GET", "path": "/broken", "headers": []}
    request = Request(scope)
    request.state.request_id = "req-internal"
    handler = app.exception_handlers[Exception]

    with caplog.at_level("ERROR"):
        response = asyncio.run(handler(request, RuntimeError("database password=secret")))

    assert response.status_code == 500
    assert json.loads(response.body) == {
        "error": {
            "code": "internal_error",
            "message": "internal error",
            "field": None,
            "request_id": "req-internal",
        }
    }
    assert b"database password=secret" not in response.body
    assert "database password=secret" in caplog.text
    assert "req-internal" in caplog.text
