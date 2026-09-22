"""add error to tasks

Revision ID: 004
Revises: 7c1e8c71111b
Create Date: 2026-09-21

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | Sequence[str] | None = "7c1e8c71111b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("error", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "error")
