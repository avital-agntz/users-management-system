"""Index registry lookups and enforce logical component uniqueness."""

from alembic import op

revision = "a14c9b27f603"
down_revision = "512e082de0d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing duplicate components must be resolved before applying this constraint.
    op.create_unique_constraint(
        "uq_components_system_kind_name", "components", ["system_id", "kind", "name"]
    )
    op.create_index("ix_components_system_id", "components", ["system_id"])
    op.create_index("ix_evidence_component_id", "evidence", ["component_id"])
    op.create_index("ix_findings_system_id", "findings", ["system_id"])
    op.create_index("ix_finding_evidence_evidence_id", "finding_evidence", ["evidence_id"])
    op.create_index("ix_audit_events_entity_type_entity_id", "audit_events", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_entity_type_entity_id", table_name="audit_events")
    op.drop_index("ix_finding_evidence_evidence_id", table_name="finding_evidence")
    op.drop_index("ix_findings_system_id", table_name="findings")
    op.drop_index("ix_evidence_component_id", table_name="evidence")
    op.drop_index("ix_components_system_id", table_name="components")
    op.drop_constraint("uq_components_system_kind_name", "components", type_="unique")
