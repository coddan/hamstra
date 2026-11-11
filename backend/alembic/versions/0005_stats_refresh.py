"""persistent seeding totals, series refresh time

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('queue', schema=None) as batch_op:
        for c in ('uploaded_base', 'uploaded_last', 'seed_base', 'seed_last'):
            batch_op.add_column(sa.Column(c, sa.BigInteger(), nullable=False, server_default='0'))
    with op.batch_alter_table('series', schema=None) as batch_op:
        batch_op.add_column(sa.Column('refreshed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('series', schema=None) as batch_op:
        batch_op.drop_column('refreshed_at')
    with op.batch_alter_table('queue', schema=None) as batch_op:
        for c in ('seed_last', 'seed_base', 'uploaded_last', 'uploaded_base'):
            batch_op.drop_column(c)
