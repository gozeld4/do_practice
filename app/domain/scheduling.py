from dataclasses import dataclass


@dataclass(frozen=True)
class PendingTask:
    task_id: str
    job_id: str
    tenant_id: str
    accelerator_type: str
    accelerators: int


@dataclass
class NodeView:
    node_id: str
    accelerator_type: str
    free: int


@dataclass(frozen=True)
class Placement:
    task_id: str
    node_id: str


@dataclass
class ScheduleResult:
    placements: list[Placement]
    unplaced: dict[str, str]


def schedule(
    pending: list[PendingTask],
    nodes: list[NodeView],
    usage_by_tenant: dict[str, int],
    quotas: dict[str, int],
) -> ScheduleResult:
    working_nodes = [NodeView(node.node_id, node.accelerator_type, node.free) for node in nodes]
    working_usage = dict(usage_by_tenant)
    placements: list[Placement] = []
    unplaced: dict[str, str] = {}

    for task in pending:
        usage = working_usage.get(task.tenant_id, 0)
        quota = quotas.get(task.tenant_id, 0)
        if usage + task.accelerators > quota:
            unplaced[task.job_id] = "quota"
            continue

        node = next(
            (
                candidate
                for candidate in working_nodes
                if candidate.accelerator_type == task.accelerator_type and candidate.free >= task.accelerators
            ),
            None,
        )
        if node is None:
            unplaced[task.job_id] = "capacity"
            continue

        node.free -= task.accelerators
        working_usage[task.tenant_id] = usage + task.accelerators
        placements.append(Placement(task.task_id, node.node_id))

    return ScheduleResult(placements, unplaced)