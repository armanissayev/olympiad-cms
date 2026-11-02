"""IDE-owned mappings; no CMS ORM models or cross-database foreign keys."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class CMSPrincipal(Base):
    __tablename__ = "cms_principals"
    __table_args__ = (UniqueConstraint("installation_id", "user_id", "contest_id", "participation_id", name="uq_cms_principal_scope"),)
    id: Mapped[str] = mapped_column(ForeignKey("development_identities.id"), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[str] = mapped_column(String(128))
    contest_id: Mapped[str] = mapped_column(String(128))
    participation_id: Mapped[str] = mapped_column(String(128))


class CMSAssertionNonce(Base):
    __tablename__ = "cms_assertion_nonces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CMSWorkspaceBinding(Base):
    # A reservation can precede workspace creation; there is deliberately no
    # workspace FK. Existing development workspace IDs cannot be adopted here.
    __tablename__ = "cms_workspace_bindings"
    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("cms_principals.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(128))
