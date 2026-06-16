"""add sort_title to tune

Revision ID: 50c587226471
Revises: 018b2ec32c0c
Create Date: 2026-06-15 09:06:37.409805

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '50c587226471'
down_revision: Union[str, Sequence[str], None] = '018b2ec32c0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors the Python sort_key() logic in SQL for the backfill.
_BACKFILL_SQL = """
UPDATE tunes SET sort_title =
    CASE
        WHEN LOWER(SUBSTR(title, 1, 4)) = 'the ' THEN SUBSTR(title, 5)
        WHEN LOWER(SUBSTR(title, 1, 3)) = 'an ' THEN SUBSTR(title, 4)
        WHEN LOWER(SUBSTR(title, 1, 2)) = 'a '  THEN SUBSTR(title, 3)
        ELSE title
    END
"""


def upgrade() -> None:
    # 1. Add nullable so existing rows don't violate the constraint yet.
    with op.batch_alter_table('tunes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sort_title', sa.String(length=200), nullable=True))

    # 2. Backfill all existing rows.
    op.execute(_BACKFILL_SQL)

    # 3. Tighten to NOT NULL and add the index.
    with op.batch_alter_table('tunes', schema=None) as batch_op:
        batch_op.alter_column('sort_title', existing_type=sa.String(length=200), nullable=False)
        batch_op.create_index(batch_op.f('ix_tunes_sort_title'), ['sort_title'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('tunes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tunes_sort_title'))
        batch_op.drop_column('sort_title')
