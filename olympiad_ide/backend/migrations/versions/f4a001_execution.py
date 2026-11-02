"""Add independent execution resources, snapshots, queue and event storage."""
from alembic import op
import sqlalchemy as sa
revision = 'f4a001'
down_revision = 'f3a001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('execution_resources', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False), sa.Column('deleted', sa.Boolean(), nullable=False))
    op.create_index('ix_execution_resources_workspace_id', 'execution_resources', ['workspace_id'])
    op.create_table('execution_resource_receipts', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('development_identities.id'), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False), sa.Column('response', sa.JSON(), nullable=False))
    op.create_table('execution_snapshots', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False), sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('configuration', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_execution_snapshots_workspace_id', 'execution_snapshots', ['workspace_id'])
    op.create_table('execution_jobs', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('development_identities.id'), nullable=False),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('snapshot_id', sa.String(36), sa.ForeignKey('execution_snapshots.id'), nullable=False),
        sa.Column('request_digest', sa.String(64), nullable=False), sa.Column('status', sa.String(40), nullable=False),
        sa.Column('tests', sa.JSON(), nullable=False), sa.Column('limits', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)), sa.Column('worker_id', sa.String(100)), sa.Column('lease_token', sa.String(36)),
        sa.Column('lease_expiration', sa.DateTime(timezone=True)), sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('last_sequence', sa.Integer(), nullable=False), sa.Column('output_bytes', sa.Integer(), nullable=False), sa.Column('result', sa.JSON()))
    op.create_index('ix_execution_jobs_workspace_id', 'execution_jobs', ['workspace_id'])
    op.create_index('ix_execution_jobs_lease_expiration', 'execution_jobs', ['lease_expiration'])
    op.create_index('ix_execution_queue', 'execution_jobs', ['status', 'created_at'])
    op.create_index('ix_execution_owner_status', 'execution_jobs', ['owner_id', 'status'])
    op.create_table('execution_events', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('execution_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False), sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.UniqueConstraint('job_id', 'sequence'))
    op.create_index('ix_execution_events_job_id', 'execution_events', ['job_id'])
    op.create_table('execution_workers', sa.Column('id', sa.String(100), primary_key=True), sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False), sa.Column('sandbox', sa.String(100), nullable=False))


def downgrade():
    for table in ('execution_events', 'execution_jobs', 'execution_snapshots', 'execution_resource_receipts', 'execution_resources', 'execution_workers'):
        op.drop_table(table)
