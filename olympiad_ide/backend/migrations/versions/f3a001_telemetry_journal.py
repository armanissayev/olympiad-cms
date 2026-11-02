"""Phase 3 independent telemetry journal; Phase 2 tables remain unchanged."""
from alembic import op
import sqlalchemy as sa

revision = 'f3a001'
down_revision = '9773627aa90c'
branch_labels = None
depends_on = None


def upgrade():
    # Frozen definitions: future ORM changes must not change this historical migration.
    op.create_table('telemetry_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('development_identities.id'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('server_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(40), nullable=False), sa.Column('integrity', sa.String(40), nullable=False),
        sa.Column('last_contiguous_sequence', sa.Integer(), nullable=False),
        sa.Column('last_monotonic_offset', sa.Float(), nullable=False),
        sa.Column('replay_state', sa.JSON(), nullable=False), sa.Column('storage_bytes', sa.Integer(), nullable=False),
        sa.Column('detected_gaps', sa.Integer(), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('workspace_id', 'owner_id', 'expires_at'):
        op.create_index('ix_telemetry_sessions_' + column, 'telemetry_sessions', [column])
    op.create_table('telemetry_events',
        sa.Column('event_id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('telemetry_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False), sa.Column('file_id', sa.String(36)),
        sa.Column('event_type', sa.String(40), nullable=False), sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('server_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('monotonic_offset', sa.Float(), nullable=False), sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('envelope', sa.JSON(), nullable=False), sa.UniqueConstraint('session_id', 'sequence'))
    op.create_index('ix_telemetry_events_session_id', 'telemetry_events', ['session_id'])
    op.create_table('telemetry_checkpoints',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('telemetry_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False), sa.Column('workspace_revision', sa.Integer(), nullable=False),
        sa.Column('document_state', sa.JSON(), nullable=False), sa.Column('state_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('envelope', sa.JSON(), nullable=False))
    for column in ('session_id', 'sequence'):
        op.create_index('ix_telemetry_checkpoints_' + column, 'telemetry_checkpoints', [column])
    op.create_table('telemetry_batches',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('telemetry_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('first_sequence', sa.Integer(), nullable=False), sa.Column('last_sequence', sa.Integer(), nullable=False),
        sa.Column('payload_digest', sa.String(64), nullable=False), sa.Column('acknowledgement_state', sa.String(20), nullable=False),
        sa.Column('chunks', sa.JSON(), nullable=False), sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('staged_bytes', sa.Integer(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_telemetry_batches_session_id', 'telemetry_batches', ['session_id'])


def downgrade():
    for table in ('telemetry_batches', 'telemetry_checkpoints', 'telemetry_events', 'telemetry_sessions'):
        op.drop_table(table)
