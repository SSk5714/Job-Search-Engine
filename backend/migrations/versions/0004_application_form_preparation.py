"""application form preparation

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 23:44:09.224511
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('apply_url', sa.Text(), nullable=True))
    op.add_column('applications', sa.Column('prepared_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('preparation', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('form_fields', sa.Column('category', sa.String(length=32), server_default='unknown', nullable=False))
    op.add_column('form_fields', sa.Column('selector', sa.Text(), nullable=True))
    op.add_column('form_fields', sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('form_fields', sa.Column('required', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('form_fields', sa.Column('position', sa.Integer(), server_default='0', nullable=False))
    op.add_column('submission_attempts', sa.Column('mode', sa.String(length=16), server_default='browser', nullable=False))
    op.add_column('submission_attempts', sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('submission_attempts', 'finished_at')
    op.drop_column('submission_attempts', 'mode')
    op.drop_column('form_fields', 'position')
    op.drop_column('form_fields', 'required')
    op.drop_column('form_fields', 'options')
    op.drop_column('form_fields', 'selector')
    op.drop_column('form_fields', 'category')
    op.drop_column('applications', 'preparation')
    op.drop_column('applications', 'prepared_at')
    op.drop_column('applications', 'apply_url')
