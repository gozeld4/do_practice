import pytest

from app.domain.states import (
    TASK_TRANSITIONS,
    IllegalTransition,
    transition,
    transition_task,
)


def test_pending_job_can_be_cancelled() -> None:
    assert transition("PENDING", "CANCELLED") == "CANCELLED"


def test_cancelled_job_cannot_be_cancelled_again() -> None:
    with pytest.raises(IllegalTransition):
        transition("CANCELLED", "CANCELLED")


def test_succeeded_job_cannot_transition() -> None:
    with pytest.raises(IllegalTransition):
        transition("SUCCEEDED", "FAILED")


def test_task_transitions_cover_lease_lifecycle() -> None:
    assert transition_task("PENDING", "LEASED") == "LEASED"
    assert transition_task("LEASED", "COMMITTED") == "COMMITTED"
    assert transition_task("LEASED", "PENDING") == "PENDING"
    assert transition_task("LEASED", "FAILED") == "FAILED"


def test_task_transition_table_is_defined() -> None:
    assert TASK_TRANSITIONS["PENDING"] == {"LEASED", "FAILED"}