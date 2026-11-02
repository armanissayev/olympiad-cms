from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow


class ExecutionResource(Base):
    __tablename__ = 'execution_resources'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer)
    value: Mapped[dict] = mapped_column(JSON)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ExecutionResourceReceipt(Base):
    __tablename__ = 'execution_resource_receipts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('development_identities.id'))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class ExecutionSnapshot(Base):
    __tablename__ = 'execution_snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    files: Mapped[list] = mapped_column(JSON)
    configuration: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionJob(Base):
    __tablename__ = 'execution_jobs'
    __table_args__ = (Index('ix_execution_queue', 'status', 'created_at'), Index('ix_execution_owner_status', 'owner_id', 'status'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('development_identities.id'))
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('execution_snapshots.id'))
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default='QUEUED')
    tests: Mapped[list] = mapped_column(JSON)
    limits: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    output_bytes: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON)


class ExecutionEvent(Base):
    __tablename__ = 'execution_events'
    __table_args__ = (UniqueConstraint('job_id', 'sequence'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('execution_jobs.id', ondelete='CASCADE'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)


class ExecutionWorker(Base):
    __tablename__ = 'execution_workers'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    capacity: Mapped[int] = mapped_column(Integer)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sandbox: Mapped[str] = mapped_column(String(100))
