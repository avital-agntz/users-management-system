"""
This module defines the SQLAlchemy models for the application.
Each model corresponds to a database table and defines the structure of the data stored in that table.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)


class AISystem(Base):
    __tablename__ = "ai_systems"

    __table_args__ = (
        # UNIQUE(repository_url, name)
        UniqueConstraint(
            "repository_url",
            "name",
            name="uq_ai_systems_repository_name",
        ),
        # CHECK constraint for environment within allowed values
        CheckConstraint(
            "environment IN ('dev', 'staging', 'prod')",
            name="ck_ai_systems_environment",
        ),
        # CHECK constraint for manifest_sha256 to be a valid SHA-256 hash
        CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ai_systems_manifest_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    repository_url: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    manifest_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Component(Base):
    """
    An AI-related part of a system; source locations belong in evidence.
    """

    __tablename__ = "components"

    __table_args__ = (
        CheckConstraint(
            # Ensure AI component kind is one of the allowed values
            "kind IN ('model', 'framework', 'tool', 'mcp_server', 'vendor', 'data_source')",
            name="ck_components_kind",
        ),
        CheckConstraint(
            # Ensure attributes is a JSON object with binary data types
            "jsonb_typeof(attributes) = 'object'",
            name="ck_components_attributes_object",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("ai_systems.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class Evidence(Base):
    """A source location supporting the presence of an AI component."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("commit_sha ~ '^[0-9a-f]{40}$'", name="ck_evidence_commit_sha"),
        CheckConstraint("line_start >= 1", name="ck_evidence_line_start"),
        CheckConstraint("line_end >= line_start", name="ck_evidence_line_range"),
        # Store relative, forward-slash repository paths; reject traversal.
        CheckConstraint(
            "length(file_path) > 0 AND file_path !~ '^(/|[A-Za-z]:)' "
            "AND strpos(file_path, '..') = 0 AND strpos(file_path, chr(92)) = 0",
            name="ck_evidence_relative_path",
        ),
        CheckConstraint(
            "snippet_sha256 IS NULL OR snippet_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_evidence_snippet_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(
        ForeignKey("components.id"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    detector: Mapped[str] = mapped_column(String, nullable=False)
    snippet_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Finding(Base):
    """A deterministic risk signal supported by linked evidence."""

    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_findings_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'accepted', 'dismissed')",
            name="ck_findings_status",
        ),
        UniqueConstraint(
            "system_id",
            "rule_id",
            "fingerprint",
            name="uq_findings_system_rule_fingerprint",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("ai_systems.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="open",
        server_default=text("'open'"),
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class FindingEvidence(Base):
    """Link findings to supporting evidence without duplicate pairs."""

    __tablename__ = "finding_evidence"

    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), primary_key=True)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id"), primary_key=True
    )


class AuditEvent(Base):
    """Record actions; application code must only insert audit events."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name="ck_audit_events_details_object",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    # The target table varies by entity_type, so this is not a foreign key.
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
