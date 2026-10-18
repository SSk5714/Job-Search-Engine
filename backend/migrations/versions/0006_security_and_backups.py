"""security and backups

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18 11:57:17.795849
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    
    op.create_table('backups',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('login_attempts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_attempts_at'), 'login_attempts', ['at'], unique=False)
    op.create_index('ix_login_attempts_user_at', 'login_attempts', ['username', 'at'], unique=False)
    op.add_column('users', sa.Column('session_version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('users', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
    


def downgrade() -> None:
    
    op.drop_column('users', 'password_changed_at')
    op.drop_column('users', 'session_version')
    op.drop_index('ix_login_attempts_user_at', table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_at'), table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_table('backups')
    
