JOB_TRANSITIONS = {
    "PENDING": {"RUNNING", "CANCELLED", "FAILED"},
    "RUNNING": {"SUCCEEDED", "FAILED", "CANCELLED"},
    "SUCCEEDED": set(),
    "FAILED": {"PENDING"},
    "CANCELLED": set(),
}

TASK_TRANSITIONS = {
    "PENDING": {"LEASED", "FAILED"},
    "LEASED": {"COMMITTED", "FAILED", "PENDING"},
    "COMMITTED": set(),
    "FAILED": set(),
}


class IllegalTransition(ValueError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"illegal transition from {current} to {target}")
        self.current = current
        self.target = target


def _transition(current: str, target: str, transitions: dict[str, set[str]]) -> str:
    if target not in transitions[current]:
        raise IllegalTransition(current, target)
    return target


def transition(current: str, target: str) -> str:
    return _transition(current, target, JOB_TRANSITIONS)


def transition_task(current: str, target: str) -> str:
    return _transition(current, target, TASK_TRANSITIONS)