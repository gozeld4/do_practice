from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.domain.scheduling import NodeView, PendingTask
from app.store.models import Job, Node, Task


def load_snapshot(session: Session) -> tuple[list[PendingTask], list[NodeView], dict[str, int]]:
    pending_rows = session.execute(
        select(
            Task.id,
            Job.id,
            Job.tenant_id,
            Job.accelerator_type,
            Job.accelerators_per_task,
        )
        .join(Job, Task.job_id == Job.id)
        .where(Task.state == "PENDING", Job.state.in_(("PENDING", "RUNNING")))
        .order_by(Job.created_at)
    )
    pending = [
        PendingTask(
            task_id=str(task_id),
            job_id=str(job_id),
            tenant_id=tenant_id,
            accelerator_type=accelerator_type,
            accelerators=accelerators,
        )
        for task_id, job_id, tenant_id, accelerator_type, accelerators in pending_rows
    ]

    leased_accelerators = func.coalesce(func.sum(Job.accelerators_per_task), 0)
    node_rows = session.execute(
        select(
            Node.id,
            Node.accelerator_type,
            (Node.capacity - leased_accelerators).label("free"),
        )
        .outerjoin(
            Task,
            and_(Task.node_id == Node.id, Task.state == "LEASED"),
        )
        .outerjoin(Job, Task.job_id == Job.id)
        .group_by(Node.id, Node.accelerator_type, Node.capacity)
        .order_by(Node.id)
    )
    nodes = [NodeView(node_id=node_id, accelerator_type=accelerator_type, free=free) for node_id, accelerator_type, free in node_rows]

    usage_rows = session.execute(
        select(Job.tenant_id, func.sum(Job.accelerators_per_task))
        .join(Task, Task.job_id == Job.id)
        .where(Task.state == "LEASED")
        .group_by(Job.tenant_id)
    )
    usage = {tenant_id: total for tenant_id, total in usage_rows}

    return pending, nodes, usage