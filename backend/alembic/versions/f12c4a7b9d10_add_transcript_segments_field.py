"""add transcript segments field

Revision ID: f12c4a7b9d10
Revises: d4f1b8a9c2d3
Create Date: 2026-03-01 00:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f12c4a7b9d10"
down_revision: Union[str, Sequence[str], None] = "d4f1b8a9c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("meetings", sa.Column("transcript_segments", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("meetings", "transcript_segments")
