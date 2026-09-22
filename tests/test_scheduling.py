from app.domain.scheduling import NodeView, PendingTask, schedule


def task(task_id: str, job_id: str, tenant_id: str, accelerator_type: str = "a100", accelerators: int = 1) -> PendingTask:
    return PendingTask(task_id, job_id, tenant_id, accelerator_type, accelerators)


def test_a100_task_never_lands_on_h100_node() -> None:
    result = schedule(
        [task("task-1", "job-1", "acme")],
        [NodeView("node-1", "h100", 4)],
        {},
        {"acme": 8},
    )

    assert result.placements == []
    assert result.unplaced == {"job-1": "capacity"}


def test_capacity_is_updated_between_tasks() -> None:
    result = schedule(
        [task("task-1", "job-1", "acme", accelerators=3), task("task-2", "job-2", "acme", accelerators=3)],
        [NodeView("node-1", "a100", 4)],
        {},
        {"acme": 8},
    )

    assert [(placement.task_id, placement.node_id) for placement in result.placements] == [("task-1", "node-1")]
    assert result.unplaced == {"job-2": "capacity"}


def test_quota_is_updated_between_tasks() -> None:
    result = schedule(
        [task("task-1", "job-1", "acme", accelerators=5), task("task-2", "job-2", "acme", accelerators=5)],
        [NodeView("node-1", "a100", 10)],
        {},
        {"acme": 8},
    )

    assert len(result.placements) == 1
    assert result.unplaced == {"job-2": "quota"}


def test_schedule_is_pure_and_uses_pending_order() -> None:
    nodes = [NodeView("node-1", "a100", 4)]
    usage = {"acme": 0}

    result = schedule(
        [task("task-1", "job-1", "acme", accelerators=2), task("task-2", "job-2", "acme", accelerators=2)],
        nodes,
        usage,
        {"acme": 8},
    )

    assert [placement.task_id for placement in result.placements] == ["task-1", "task-2"]
    assert nodes == [NodeView("node-1", "a100", 4)]
    assert usage == {"acme": 0}


def test_empty_node_list_leaves_task_unplaced_for_capacity() -> None:
    result = schedule([task("task-1", "job-1", "acme")], [], {}, {"acme": 8})

    assert result.placements == []
    assert result.unplaced == {"job-1": "capacity"}


def test_tenant_at_quota_is_refused() -> None:
    result = schedule([task("task-1", "job-1", "acme")], [NodeView("node-1", "a100", 4)], {"acme": 8}, {"acme": 8})

    assert result.placements == []
    assert result.unplaced == {"job-1": "quota"}