"""settings source options matcher

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 22:45:53.612398
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.add_column('job_match_evaluations', sa.Column('matcher', sa.String(length=16), server_default='rules', nullable=False))
    op.alter_column('job_match_evaluations', 'model_version',
               existing_type=sa.VARCHAR(length=64),
               type_=sa.String(length=128),
               existing_nullable=False)
    op.add_column('search_configs', sa.Column('source_options', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('job_sources', sa.Column('live_verified_at', sa.DateTime(timezone=True), nullable=True))
    # 0001 declared this FK with use_alter inside create_table, which Alembic skips; create it here.
    op.create_foreign_key('fk_profile_current_version', 'candidate_profiles', 'profile_versions',
                          ['current_version_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_profile_current_version', 'candidate_profiles', type_='foreignkey')
    op.drop_column('job_sources', 'live_verified_at')
    op.drop_column('search_configs', 'source_options')
    op.alter_column('job_match_evaluations', 'model_version',
               existing_type=sa.String(length=128),
               type_=sa.VARCHAR(length=64),
               existing_nullable=False)
    op.drop_column('job_match_evaluations', 'matcher')
    op.drop_table('app_settings')
