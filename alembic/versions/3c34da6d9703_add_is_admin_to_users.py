"""add is_admin to users

Revision ID: 3c34da6d9703
Revises: 0e6a71e04151
Create Date: 2026-06-20 11:27:54.177191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c34da6d9703'
down_revision: Union[str, None] = '0e6a71e04151'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default=sa.false() renders the correct literal per dialect
    # (FALSE on PostgreSQL, 0 on SQLite), and backfills existing rows.
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'is_admin')
