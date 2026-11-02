"""Add isolated DAP session metadata and bounded durable protocol transport."""
from alembic import op
import sqlalchemy as sa
revision='f6a001'
down_revision='f5a001'
branch_labels=None
depends_on=None

def upgrade():
    from app.debug_models import DebugSession,DebugMessage,DebugWorker
    for model in [DebugSession,DebugMessage,DebugWorker]:model.__table__.create(op.get_bind())

def downgrade():
    for name in ['debug_sessions','debug_messages','debug_workers']:
        if op.get_bind().execute(sa.text('SELECT count(*) FROM '+name)).scalar():raise RuntimeError('Debug history exists; retain metadata during rollback')
    for name in ['debug_messages','debug_sessions','debug_workers']:op.drop_table(name)
