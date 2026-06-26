"""add_warmup_default_tempo_and_warmup_tempos

Revision ID: 661611a1540d
Revises: 026536c6736a
Create Date: 2026-06-25 20:54:38.510774

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '661611a1540d'
down_revision: Union[str, Sequence[str], None] = '026536c6736a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('warmup_tempos',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('warmup_id', sa.Integer(), nullable=False),
    sa.Column('tempo', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['warmup_id'], ['warmup_items.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'warmup_id')
    )
    with op.batch_alter_table('warmup_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_tempo', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('warmup_items', schema=None) as batch_op:
        batch_op.drop_column('default_tempo')

    op.drop_table('warmup_tempos')
