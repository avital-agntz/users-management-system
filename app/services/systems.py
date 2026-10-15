"""
Query recorded AI systems independently of HTTP request handling.
"""

from typing import get_args

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AISystem, Component, Evidence
from app.schemas import (AIBOMResponse, ComponentKind, ComponentResponse,
                         Environment, EvidenceResponse, SystemDetail,
                         SystemsPage, SystemSummary)


def list_systems(
    session: Session,
    environment: Environment | None = None,
    limit: int = 20,
    offset: int = 0,
) -> SystemsPage:
    """Return a page of systems visible to any authenticated user.
    The caller owns the session and validates the query parameters.
    """
    # All the AI systems in the database
    query = select(AISystem)
    # Count of total number of matching systems
    count_query = select(func.count()).select_from(AISystem)

    # Apply Environment filter if provided
    if environment is not None:
        query = query.where(AISystem.environment == environment)
        count_query = count_query.where(AISystem.environment == environment)

    total = session.scalar(count_query)

    # Order the results by ID, apply offset and limit
    systems = session.scalars(
        query.order_by(AISystem.id).offset(offset).limit(limit)
    ).all()

    # Convert ORM attributes to SystemsPage instance
    return SystemsPage(
        items=[SystemSummary.model_validate(system) for system in systems],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_system_detail(session: Session, system_id: int) -> SystemDetail | None:
    """Read one system with its components and evidence, or return None.

    Three bounded queries avoid one evidence query per component. The caller
    owns the session and translates a missing system into an HTTP response.
    """
    system = session.get(AISystem, system_id)

    # The system was not found
    if system is None:
        return None

    # SQL query to fetch all components for the given system ID
    components = session.scalars(
        select(Component).where(Component.system_id == system_id).order_by(Component.id)
    ).all()
    # The join restricts evidence to this system without a large IN-list.
    locations = session.scalars(
        select(Evidence)
        .join(Component, Evidence.component_id == Component.id)
        .where(Component.system_id == system_id)
        .order_by(Evidence.id)
    ).all()

    # Build a mapping from component ID to its evidence responses
    evidence_by_component = {}
    for location in locations:
        evidence_by_component.setdefault(location.component_id, []).append(
            EvidenceResponse.model_validate(location)
        )

    # Build response objects while the session is open; no lazy ORM access later.
    return SystemDetail(
        **SystemSummary.model_validate(system).model_dump(),
        components=[
            ComponentResponse(
                id=component.id,
                kind=component.kind,
                name=component.name,
                version=component.version,
                attributes=component.attributes,
                evidence=evidence_by_component.get(component.id, []),
            )
            for component in components
        ],
    )


def get_system_aibom(session: Session, system_id: int) -> AIBOMResponse | None:
    """
    Group the existing system detail; reuse its three-query read path.
    """
    detail = get_system_detail(session, system_id)
    if detail is None:
        return None

    # Always expose all component categories, with empty lists where no component exists.
    groups = {kind: [] for kind in get_args(ComponentKind)}
    for component in detail.components:
        groups[component.kind].append(component)

    return AIBOMResponse(
        system=SystemSummary.model_validate(detail),
        components_by_kind=groups,
    )
