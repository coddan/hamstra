"""music albums

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'albums',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mbid', sa.String(), nullable=False),
        sa.Column('artist', sa.String(), nullable=False),
        sa.Column('artist_mbid', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(), nullable=True),
        sa.Column('cover_url', sa.String(), nullable=True),
        sa.Column('monitored', sa.Boolean(), nullable=False),
        sa.Column('has_files', sa.Boolean(), nullable=False),
        sa.Column('file_format', sa.String(), nullable=True),
        sa.Column('genre', sa.String(), nullable=False, server_default=''),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('root_folder_id', sa.Integer(), nullable=True),
        sa.Column('added', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['root_folder_id'], ['root_folders.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mbid'),
    )
    with op.batch_alter_table('queue', schema=None) as batch_op:
        batch_op.add_column(sa.Column('album_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_queue_album', 'albums', ['album_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('queue', schema=None) as batch_op:
        batch_op.drop_constraint('fk_queue_album', type_='foreignkey')
        batch_op.drop_column('album_id')
    op.drop_table('albums')
