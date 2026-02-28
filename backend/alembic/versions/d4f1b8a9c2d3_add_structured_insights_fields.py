"""add structured insights fields

Revision ID: d4f1b8a9c2d3
Revises: b3d9a7f4c1e2
Create Date: 2026-02-28 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f1b8a9c2d3"
down_revision: Union[str, Sequence[str], None] = "b3d9a7f4c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("meetings", sa.Column("key_points", sa.JSON(), nullable=True))
    op.add_column("meetings", sa.Column("decisions", sa.JSON(), nullable=True))
    op.add_column("meetings", sa.Column("action_items", sa.JSON(), nullable=True))
    op.add_column("meetings", sa.Column("risks", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("meetings", "risks")
    op.drop_column("meetings", "action_items")
    op.drop_column("meetings", "decisions")
    op.drop_column("meetings", "key_points")
