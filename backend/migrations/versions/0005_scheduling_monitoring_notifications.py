"""scheduling monitoring notifications

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 00:11:57.023857
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('heartbeats',
    sa.Column('component', sa.String(length=32), nullable=False),
    sa.Column('beat_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('interval_s', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('component')
    )
    op.create_table('notification_deliveries',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('notification_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('notification_id', 'channel', name='uq_delivery_per_channel')
    )
    op.create_index('ix_deliveries_due', 'notification_deliveries', ['status', 'next_attempt_at'], unique=False)
    op.create_table('schedule_dispatches',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('config_id', sa.UUID(), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('outcome', sa.String(length=24), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['config_id'], ['search_configs.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['search_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('config_id', 'due_at', name='uq_schedule_dispatch_due')
    )
    op.create_index(op.f('ix_schedule_dispatches_config_id'), 'schedule_dispatches', ['config_id'], unique=False)
    op.add_column('notifications', sa.Column('dedup_key', sa.String(length=160), nullable=True))
    op.add_column('notifications', sa.Column('component', sa.String(length=64), nullable=True))
    op.add_column('notifications', sa.Column('run_id', sa.UUID(), nullable=True))
    op.add_column('notifications', sa.Column('task_id', sa.UUID(), nullable=True))
    op.add_column('notifications', sa.Column('likely_cause', sa.Text(), nullable=True))
    op.add_column('notifications', sa.Column('remediation', sa.Text(), nullable=True))
    op.add_column('notifications', sa.Column('workflow_paused', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('notifications', sa.Column('link', sa.String(length=255), nullable=True))
    op.add_column('notifications', sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('notifications', sa.Column('occurrences', sa.Integer(), server_default='1', nullable=False))
    op.add_column('notifications', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notifications', sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notifications', sa.Column('resolved_by', sa.String(length=16), nullable=True))
    op.create_index('uq_notifications_dedup', 'notifications', ['dedup_key'], unique=True, postgresql_where=sa.text('dedup_key IS NOT NULL'))
    op.add_column('search_configs', sa.Column('timezone', sa.String(length=64), server_default='Europe/Berlin', nullable=False))
    op.add_column('search_configs', sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('search_configs', sa.Column('paused_reason', sa.Text(), nullable=True))
    op.add_column('search_configs', sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('search_configs', sa.Column('resumed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_search_configs_next_run_at'), 'search_configs', ['next_run_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_search_configs_next_run_at'), table_name='search_configs')
    op.drop_column('search_configs', 'resumed_at')
    op.drop_column('search_configs', 'paused_at')
    op.drop_column('search_configs', 'paused_reason')
    op.drop_column('search_configs', 'next_run_at')
    op.drop_column('search_configs', 'timezone')
    op.drop_index('uq_notifications_dedup', table_name='notifications', postgresql_where=sa.text('dedup_key IS NOT NULL'))
    op.drop_column('notifications', 'resolved_by')
    op.drop_column('notifications', 'acknowledged_at')
    op.drop_column('notifications', 'last_seen_at')
    op.drop_column('notifications', 'occurrences')
    op.drop_column('notifications', 'context')
    op.drop_column('notifications', 'link')
    op.drop_column('notifications', 'workflow_paused')
    op.drop_column('notifications', 'remediation')
    op.drop_column('notifications', 'likely_cause')
    op.drop_column('notifications', 'task_id')
    op.drop_column('notifications', 'run_id')
    op.drop_column('notifications', 'component')
    op.drop_column('notifications', 'dedup_key')
    op.drop_index(op.f('ix_schedule_dispatches_config_id'), table_name='schedule_dispatches')
    op.drop_table('schedule_dispatches')
    op.drop_index('ix_deliveries_due', table_name='notification_deliveries')
    op.drop_table('notification_deliveries')
    op.drop_table('heartbeats')
