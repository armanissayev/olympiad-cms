from datetime import datetime
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow


class TelemetrySession(Base):
    __tablename__ = 'telemetry_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('development_identities.id'), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default='recording')
    integrity: Mapped[str] = mapped_column(String(40), default='Complete')
    last_contiguous_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_monotonic_offset: Mapped[float] = mapped_column(Float, default=0)
    replay_state: Mapped[dict] = mapped_column(JSON)
    storage_bytes: Mapped[int] = mapped_column(Integer, default=0)
    detected_gaps: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TelemetryEvent(Base):
    __tablename__ = 'telemetry_events'
    __table_args__ = (UniqueConstraint('session_id', 'sequence'),)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('telemetry_sessions.id', ondelete='CASCADE'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[int] = mapped_column(Integer)
    client_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    monotonic_offset: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)
    envelope: Mapped[dict] = mapped_column(JSON)


class TelemetryCheckpoint(Base):
    __tablename__ = 'telemetry_checkpoints'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('telemetry_sessions.id', ondelete='CASCADE'), index=True)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    workspace_revision: Mapped[int] = mapped_column(Integer)
    document_state: Mapped[dict] = mapped_column(JSON)
    state_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    envelope: Mapped[dict] = mapped_column(JSON)


class TelemetryBatch(Base):
    __tablename__ = 'telemetry_batches'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('telemetry_sessions.id', ondelete='CASCADE'), index=True)
    first_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    payload_digest: Mapped[str] = mapped_column(String(64))
    acknowledgement_state: Mapped[str] = mapped_column(String(20), default='staging')
    chunks: Mapped[dict] = mapped_column(JSON, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    staged_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
