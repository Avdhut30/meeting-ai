"""add meeting task tracking fields

Revision ID: b3d9a7f4c1e2
Revises: eac16ff371f9
Create Date: 2026-02-27 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3d9a7f4c1e2"
down_revision: Union[str, Sequence[str], None] = "eac16ff371f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("meetings", sa.Column("processing_task_id", sa.String(length=255), nullable=True))
    op.add_column("meetings", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("meetings", "processing_started_at")
    op.drop_column("meetings", "processing_task_id")
