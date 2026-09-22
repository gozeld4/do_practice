from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.store.models import Task


def update_if_current(
    session: Session,
    lease_id: str,
    epoch: int,
    now: datetime,
    **changes: Any,
) -> bool:
    statement = (
        update(Task)
        .where(
            Task.lease_id == lease_id,
            Task.epoch == epoch,
            Task.state == "LEASED",
            Task.expires_at > now,
        )
        .values(**changes)
    )
    return session.execute(statement).rowcount == 1