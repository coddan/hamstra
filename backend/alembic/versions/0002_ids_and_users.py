"""ids and users

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False),
        sa.Column('created', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )
    with op.batch_alter_table('movies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('imdb_id', sa.String(), nullable=True))
    with op.batch_alter_table('series', schema=None) as batch_op:
        batch_op.add_column(sa.Column('imdb_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('tvdb_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('series', schema=None) as batch_op:
        batch_op.drop_column('tvdb_id')
        batch_op.drop_column('imdb_id')
    with op.batch_alter_table('movies', schema=None) as batch_op:
        batch_op.drop_column('imdb_id')
    op.drop_table('users')
