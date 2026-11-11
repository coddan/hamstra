"""richer quality profiles

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

ALL = "remux,bluray,web-dl,webrip,hdtv,dvd"


def upgrade() -> None:
    with op.batch_alter_table('quality_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sources', sa.String(), nullable=False, server_default=ALL))
        batch_op.add_column(sa.Column('source_order', sa.String(), nullable=False, server_default=ALL))
        batch_op.add_column(sa.Column('prefer_words', sa.String(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('reject_words', sa.String(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('prefer_hdr', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('upgrade_allowed', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE quality_profiles SET is_default = 1 WHERE id = (SELECT MIN(id) FROM quality_profiles)")


def downgrade() -> None:
    with op.batch_alter_table('quality_profiles', schema=None) as batch_op:
        for c in ('is_default', 'upgrade_allowed', 'prefer_hdr', 'reject_words', 'prefer_words', 'source_order', 'sources'):
            batch_op.drop_column(c)
