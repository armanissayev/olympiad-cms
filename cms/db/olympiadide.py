# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CMS-owned transactional receipts for native IDE submission intents.

Source bytes remain in normal CMS File storage. This table contains immutable
scope, exact byte hashes and browser correlation, never editor telemetry.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from . import Base, Participation, Submission


class OlympiadIDEReceipt(Base):
    __tablename__ = "olympiad_ide_receipts"
    __table_args__ = (
        UniqueConstraint("installation_id", "participation_id", "intent_id",
                         name="uq_olympiad_ide_scope_intent"),
        UniqueConstraint("submission_id", name="uq_olympiad_ide_submission"),
        UniqueConstraint("external_id", name="uq_olympiad_ide_external"),
    )
    id = Column(Integer, primary_key=True)
    installation_id = Column(String(128), nullable=False)
    intent_id = Column(String(36), nullable=False)
    participation_id = Column(Integer, ForeignKey(
        Participation.id, onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    participation = relationship(Participation)
    submission_id = Column(Integer, ForeignKey(
        Submission.id, onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    submission = relationship(Submission, back_populates="olympiad_ide_receipts")
    request_digest = Column(String(64), nullable=False)
    external_id = Column(String(128), nullable=False)
    identity_scope = Column(JSONB, nullable=False)
    source_manifest = Column(JSONB, nullable=False)
    correlation = Column(JSONB, nullable=False)
    received_at = Column(DateTime, nullable=False)
