"""
Create deterministic fingerprints of validated scan reports.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AISystem, AuditEvent, Component, Evidence, User
from app.schemas import ScanReport


def _canonical_json(value: object) -> str:
    """Return a canonical JSON representation of the value."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fingerprint_scan(report: ScanReport) -> str:
    """Hash report content independently of component/evidence ordering.

    Include validated defaults, retain duplicate evidence, and preserve lists
    inside attributes because their order may carry meaning.
    """
    # model_dump creates fresh containers; sorting never mutates the input model.
    data = report.model_dump(mode="json")
    for component in data["components"]:
        # Use every evidence field, including snippet hashes, to break ties.
        component["evidence"].sort(key=_canonical_json)
    data["components"].sort(
        key=lambda component: (component["kind"], component["name"])
    )
    canonical = _canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScanConflictError(Exception):
    """Different scan content already exists for this repository and system."""


class ScanActorError(Exception):
    """The authenticated actor no longer exists."""


class ScanOwnerError(Exception):
    """The supplied owner does not exist."""


@dataclass(frozen=True)
class RecordedScan:
    system: dict[str, Any]
    created: bool


def _system_data(system: AISystem) -> dict[str, Any]:
    """Return a dict of system fields suitable for JSON serialization."""
    return {
        "id": system.id,
        "name": system.name,
        "repository_url": system.repository_url,
        "environment": system.environment,
        "owner_user_id": system.owner_user_id,
        "created_at": system.created_at,
    }


def _existing_scan(session: Session, report: ScanReport, fingerprint: str):
    """
    Return a RecordedScan for an existing system with the same fingerprint.
    """
    # SQL query to find an existing system with the same manifest SHA256 fingerprint
    existing = session.scalar(
        select(AISystem).where(AISystem.manifest_sha256 == fingerprint)
    )
    # If a system with the same fingerprint exists, return it as a RecordedScan.
    if existing is not None:
        return RecordedScan(_system_data(existing), created=False)
    # If no system with the same fingerprint exists, check for a system with the same repository URL and name
    existing = session.scalar(
        select(AISystem).where(
            AISystem.repository_url == report.system.repository_url,
            AISystem.name == report.system.name,
        )
    )
    # If a system with the same repository URL and name exists, raise a ScanConflictError
    if existing is not None:
        raise ScanConflictError(
            "Different scan content already exists for this system."
        )
    # No existing system found
    return None


def record_scan(
    session: Session, report: ScanReport, actor_user_id: int
) -> RecordedScan:
    """Record a validated scan atomically using a new session.

    Owns the transaction. Repeats return the existing system without another
    audit event; only a newly recorded scan creates an import event.
    """
    if session.in_transaction():
        raise ValueError(
            "record_scan requires a session without an active transaction."
        )
    # Revalidate report to ensure that it is still valid and to apply any default values
    report = ScanReport.model_validate(report.model_dump(mode="json"))
    # Compute the fingerprint of the report
    fingerprint = fingerprint_scan(report)

    try:
        with session.begin():
            # If the actor user does not exist, raise a ScanActorError
            if session.get(User, actor_user_id) is None:
                raise ScanActorError("Authenticated user no longer exists.")
            # Check for an existing scan using the given session
            existing = _existing_scan(session, report, fingerprint)
            # If an existing scan is found, return it
            if existing is not None:
                return existing
            # If the owner user ID is provided and does not exist, raise a ScanOwnerError
            if (
                report.system.owner_user_id is not None
                and session.get(User, report.system.owner_user_id) is None
            ):
                raise ScanOwnerError("System owner does not exist.")

            # No existing scan found, create a new AISystem record

            system = AISystem(**report.system.model_dump(), manifest_sha256=fingerprint)
            session.add(system)
            session.flush()  # Obtain the ID without committing partial work.
            for item in report.components:
                # Create a new Component record for each component in the report
                component = Component(
                    system_id=system.id, **item.model_dump(exclude={"evidence"})
                )
                session.add(component)
                session.flush()
                for location in item.evidence:
                    # Create a new Evidence record for each evidence item in the component
                    session.add(
                        Evidence(
                            component_id=component.id,
                            commit_sha=report.commit_sha,
                            **location.model_dump(),
                        )
                    )

            # Create an audit event for the import action

            session.add(
                AuditEvent(
                    actor_user_id=actor_user_id,
                    action="import",
                    entity_type="ai_system",
                    entity_id=system.id,
                    details={
                        "manifest_sha256": fingerprint,
                        "component_count": len(report.components),
                    },
                )
            )
            session.flush()
            # Return a RecordedScan for the newly created system
            result = RecordedScan(_system_data(system), created=True)
        return result

    # Handle potential integrity errors that may arise from concurrent scans

    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint not in {
            "uq_ai_systems_repository_name",
            "ai_systems_manifest_sha256_key",
        }:
            raise

        # If the integrity error is due to a unique constraint violation,
        # check for an existing scan again
        with session.begin():
            existing = _existing_scan(session, report, fingerprint)
            if existing is not None:
                return existing
        raise
