"""Durable bounded interactive sessions; separate from official CMS submissions."""
from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow

class DebugSession(Base):
    __tablename__='debug_sessions'
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('development_identities.id'),index=True)
    workspace_id: Mapped[str]=mapped_column(ForeignKey('workspaces.id'),index=True)
    snapshot: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(30),default='QUEUED',index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str|None]=mapped_column(String(36))
    heartbeat: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool]=mapped_column(Boolean,default=False)
    output_bytes: Mapped[int]=mapped_column(Integer,default=0)
    last_event: Mapped[int]=mapped_column(Integer,default=0)
    attach_hash: Mapped[str|None]=mapped_column(String(64))
    attach_expires: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    error: Mapped[str|None]=mapped_column(String(1000))

class DebugMessage(Base):
    __tablename__='debug_messages'
    __table_args__=(UniqueConstraint('session_id','direction','sequence'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    session_id: Mapped[str]=mapped_column(ForeignKey('debug_sessions.id',ondelete='CASCADE'),index=True)
    direction: Mapped[str]=mapped_column(String(10))
    sequence: Mapped[int]=mapped_column(Integer)
    payload: Mapped[dict]=mapped_column(JSON)

class DebugWorker(Base):
    __tablename__='debug_workers'
    id: Mapped[str]=mapped_column(String(100),primary_key=True)
    last_seen: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    languages: Mapped[list]=mapped_column(JSON)
