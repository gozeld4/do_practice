import pytest
from sqlalchemy import text

from app.store.db import engine


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE tasks, jobs RESTART IDENTITY CASCADE"))