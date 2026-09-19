"""initial schema

Revision ID: 0001
Revises: 
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_events',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=True),
    sa.Column('device_id', sa.String(length=64), nullable=True),
    sa.Column('event', sa.String(length=60), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index('ix_audit_events_event_created_at', 'audit_events', ['event', 'created_at'], unique=False)
    op.create_index('ix_audit_events_user_id_created_at', 'audit_events', ['user_id', 'created_at'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=40), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=120), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
    sa.UniqueConstraint('dedupe_key', name=op.f('uq_jobs_dedupe_key'))
    )
    op.create_index('ix_jobs_status_run_after', 'jobs', ['status', 'run_after'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('issuer', sa.String(length=300), nullable=True),
    sa.Column('subject', sa.String(length=300), nullable=True),
    sa.Column('display_name', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('issuer', 'subject', name='uq_users_issuer_subject')
    )
    op.create_table('cli_auth_requests',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('device_name', sa.String(length=200), nullable=False),
    sa.Column('device_os', sa.String(length=50), nullable=False),
    sa.Column('device_arch', sa.String(length=50), nullable=False),
    sa.Column('flow_version', sa.String(length=40), nullable=False),
    sa.Column('code_challenge', sa.String(length=128), nullable=False),
    sa.Column('state', sa.String(length=200), nullable=False),
    sa.Column('nonce', sa.String(length=200), nullable=False),
    sa.Column('user_code', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('denied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_cli_auth_requests_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cli_auth_requests'))
    )
    op.create_index('ix_cli_auth_requests_device_id', 'cli_auth_requests', ['device_id'], unique=False)
    op.create_index('ix_cli_auth_requests_expires_at', 'cli_auth_requests', ['expires_at'], unique=False)
    op.create_table('devices',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('os', sa.String(length=50), nullable=False),
    sa.Column('architecture', sa.String(length=50), nullable=False),
    sa.Column('flow_version', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_devices_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_devices'))
    )
    op.create_index('ix_devices_user_id', 'devices', ['user_id'], unique=False)
    op.create_table('commands',
    sa.Column('command_id', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=80), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('type', sa.String(length=40), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivery_count', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_commands_device_id_devices')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_commands_user_id_users')),
    sa.PrimaryKeyConstraint('command_id', name=op.f('pk_commands'))
    )
    op.create_index('ix_commands_device_id_status_created_at', 'commands', ['device_id', 'status', 'created_at'], unique=False)
    op.create_index('ix_commands_session_id_created_at', 'commands', ['session_id', 'created_at'], unique=False)
    op.create_index('ix_commands_user_id_created_at', 'commands', ['user_id', 'created_at'], unique=False)
    op.create_table('device_presence',
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('connection_id', sa.String(length=64), nullable=True),
    sa.Column('connected', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('health', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.Column('active_sessions', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.Column('flow_version', sa.String(length=40), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_device_presence_device_id_devices')),
    sa.PrimaryKeyConstraint('device_id', name=op.f('pk_device_presence'))
    )
    op.create_table('refresh_tokens',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('family_id', sa.String(length=40), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by', sa.String(length=40), nullable=True),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_refresh_tokens_device_id_devices')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index('ix_refresh_tokens_device_id', 'refresh_tokens', ['device_id'], unique=False)
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('goal', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('goal_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status_sequence', sa.Integer(), server_default='0', nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_sessions_device_id_devices')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index('ix_sessions_device_id', 'sessions', ['device_id'], unique=False)
    op.create_index('ix_sessions_user_id_started_at', 'sessions', ['user_id', 'started_at'], unique=False)
    op.create_table('events',
    sa.Column('session_id', sa.String(length=80), nullable=False),
    sa.Column('event_id', sa.String(length=80), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=48), nullable=False),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('server_received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_events_session_id_sessions')),
    sa.PrimaryKeyConstraint('session_id', 'event_id', name=op.f('pk_events')),
    sa.UniqueConstraint('session_id', 'sequence', name='uq_events_session_sequence')
    )
    op.create_index('ix_events_session_id_sequence', 'events', ['session_id', 'sequence'], unique=False)
    op.create_index('ix_events_session_id_type_sequence', 'events', ['session_id', 'type', 'sequence'], unique=False)
    op.create_table('interventions',
    sa.Column('session_id', sa.String(length=80), nullable=False),
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.String(length=100), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.Column('server_received_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_interventions_session_id_sessions')),
    sa.PrimaryKeyConstraint('session_id', 'id', name=op.f('pk_interventions'))
    )
    op.create_index('ix_interventions_session_id_timestamp', 'interventions', ['session_id', 'timestamp'], unique=False)
    op.create_table('observations',
    sa.Column('session_id', sa.String(length=80), nullable=False),
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('server_received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('activity', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=24), nullable=False),
    sa.Column('goal_alignment', sa.Float(), nullable=True),
    sa.Column('progress_signal', sa.Float(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('task_phase', sa.String(length=40), nullable=True),
    sa.Column('application', sa.String(length=200), nullable=True),
    sa.Column('activity_type', sa.String(length=40), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('blocker', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_observations_session_id_sessions')),
    sa.PrimaryKeyConstraint('session_id', 'id', name=op.f('pk_observations')),
    sa.UniqueConstraint('session_id', 'sequence', name='uq_observations_session_sequence')
    )
    op.create_index('ix_observations_session_id_sequence', 'observations', ['session_id', 'sequence'], unique=False)
    op.create_table('session_entities',
    sa.Column('session_id', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_entities_session_id_sessions')),
    sa.PrimaryKeyConstraint('session_id', 'kind', 'id', name=op.f('pk_session_entities'))
    )
    op.create_index('ix_session_entities_kind_status', 'session_entities', ['kind', 'status'], unique=False)
    op.create_index('ix_session_entities_session_id_kind_updated_at', 'session_entities', ['session_id', 'kind', 'updated_at'], unique=False)
    op.create_table('session_summaries',
    sa.Column('session_id', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=24), nullable=False),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_summaries_session_id_sessions')),
    sa.PrimaryKeyConstraint('session_id', 'version', name=op.f('pk_session_summaries'))
    )
    op.create_table('task_segments',
    sa.Column('session_id', sa.String(length=80), nullable=False),
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('activity', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=24), nullable=False),
    sa.Column('application', sa.String(length=200), nullable=True),
    sa.Column('alignment', sa.Float(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('observation_count', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_task_segments_session_id_sessions')),
    sa.PrimaryKeyConstraint('session_id', 'id', name=op.f('pk_task_segments'))
    )
    op.create_index('ix_task_segments_session_id_start_at', 'task_segments', ['session_id', 'start_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_task_segments_session_id_start_at', table_name='task_segments')
    op.drop_table('task_segments')
    op.drop_table('session_summaries')
    op.drop_index('ix_session_entities_session_id_kind_updated_at', table_name='session_entities')
    op.drop_index('ix_session_entities_kind_status', table_name='session_entities')
    op.drop_table('session_entities')
    op.drop_index('ix_observations_session_id_sequence', table_name='observations')
    op.drop_table('observations')
    op.drop_index('ix_interventions_session_id_timestamp', table_name='interventions')
    op.drop_table('interventions')
    op.drop_index('ix_events_session_id_type_sequence', table_name='events')
    op.drop_index('ix_events_session_id_sequence', table_name='events')
    op.drop_table('events')
    op.drop_index('ix_sessions_user_id_started_at', table_name='sessions')
    op.drop_index('ix_sessions_device_id', table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_device_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_table('device_presence')
    op.drop_index('ix_commands_user_id_created_at', table_name='commands')
    op.drop_index('ix_commands_session_id_created_at', table_name='commands')
    op.drop_index('ix_commands_device_id_status_created_at', table_name='commands')
    op.drop_table('commands')
    op.drop_index('ix_devices_user_id', table_name='devices')
    op.drop_table('devices')
    op.drop_index('ix_cli_auth_requests_expires_at', table_name='cli_auth_requests')
    op.drop_index('ix_cli_auth_requests_device_id', table_name='cli_auth_requests')
    op.drop_table('cli_auth_requests')
    op.drop_table('users')
    op.drop_index('ix_jobs_status_run_after', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_audit_events_user_id_created_at', table_name='audit_events')
    op.drop_index('ix_audit_events_event_created_at', table_name='audit_events')
    op.drop_table('audit_events')
