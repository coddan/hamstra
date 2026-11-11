"""requests, movie release dates, stall tracking

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('movies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('release_date', sa.Date(), nullable=True))
    with op.batch_alter_table('queue', schema=None) as batch_op:
        batch_op.add_column(sa.Column('progress_changed_at', sa.DateTime(), nullable=True))
    op.create_table(
        'requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('poster_url', sa.String(), nullable=True),
        sa.Column('overview', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('requests')
    with op.batch_alter_table('queue', schema=None) as batch_op:
        batch_op.drop_column('progress_changed_at')
    with op.batch_alter_table('movies', schema=None) as batch_op:
        batch_op.drop_column('release_date')
