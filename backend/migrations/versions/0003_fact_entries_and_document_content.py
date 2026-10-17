"""fact entries and document content

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 23:13:27.141141
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('documents', sa.Column('generator', sa.String(length=16), server_default='template', nullable=False))
    op.add_column('documents', sa.Column('model_version', sa.String(length=128), nullable=True))
    op.add_column('profile_facts', sa.Column('entry', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('profile_facts', 'entry')
    op.drop_column('documents', 'model_version')
    op.drop_column('documents', 'generator')
    op.drop_column('documents', 'content')
