"""Add CMS principal mappings and single-use private assertion nonces.

Existing owners, workspaces, journals and receipts are untouched. This migration
belongs only to the IDE database; it must never run against CMS metadata.
"""
from alembic import op
import sqlalchemy as sa

revision = "f5a001"
down_revision = "f4a001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("cms_principals",
        sa.Column("id", sa.String(36), sa.ForeignKey("development_identities.id"), primary_key=True),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("contest_id", sa.String(128), nullable=False),
        sa.Column("participation_id", sa.String(128), nullable=False),
        sa.UniqueConstraint("installation_id", "user_id", "contest_id", "participation_id", name="uq_cms_principal_scope"))
    op.create_table("cms_workspace_bindings",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(36), sa.ForeignKey("cms_principals.id"), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False))
    op.create_index("ix_cms_workspace_bindings_principal_id", "cms_workspace_bindings", ["principal_id"])
    op.create_table("cms_assertion_nonces", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cms_assertion_nonces_expires_at", "cms_assertion_nonces", ["expires_at"])


def downgrade():
    # Empty test/new installations can roll back. Never discard real mappings
    # or consumed assertions; feature-disable rollback retains these tables.
    connection = op.get_bind()
    for name in ("cms_principals", "cms_workspace_bindings", "cms_assertion_nonces"):
        if connection.execute(sa.text("SELECT count(*) FROM " + name)).scalar():
            raise RuntimeError("CMS identity tables contain data; disable the feature without dropping mappings")
    op.drop_table("cms_assertion_nonces")
    op.drop_table("cms_workspace_bindings")
    op.drop_table("cms_principals")
