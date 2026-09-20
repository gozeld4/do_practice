from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.store.db import get_session


class FakeSession:
    def execute(self, statement: object) -> None:
        assert str(statement) == "SELECT 1"


def fake_session() -> Generator[FakeSession, None, None]:
    yield FakeSession()


def failing_session() -> Generator[FakeSession, None, None]:
    class FailingSession:
        def execute(self, statement: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("database unavailable"))

    yield FailingSession()


def test_readyz_when_database_is_available() -> None:
    app.dependency_overrides[get_session] = fake_session

    try:
        response = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_when_database_is_unavailable() -> None:
    app.dependency_overrides[get_session] = failing_session

    try:
        response = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}