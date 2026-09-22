from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import get_settings
from app.domain.apply import apply
from app.domain.scheduling import ScheduleResult, schedule
from app.domain.snapshot import load_snapshot


def run_one_tick(session: Session, clock: Clock) -> ScheduleResult:
    settings = get_settings()
    pending, nodes, usage = load_snapshot(session)
    result = schedule(pending, nodes, usage, settings.tenant_quotas)
    apply(session, result, clock, settings)
    return result