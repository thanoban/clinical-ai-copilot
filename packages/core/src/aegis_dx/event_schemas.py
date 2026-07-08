from __future__ import annotations

from aegis_dx.domain import EventSchemaDefinition


CASE_EVENT_SCHEMAS: dict[str, EventSchemaDefinition] = {
    "case.submitted": EventSchemaDefinition(
        event_type="case.submitted",
        schema_version="1.0.0",
        description="Case intake accepted into the workflow.",
        required_payload_fields=["trace_id", "site_id", "source_system"],
    ),
    "workflow.deidentified": EventSchemaDefinition(
        event_type="workflow.deidentified",
        schema_version="1.0.0",
        description="Artifact de-identification completed.",
        required_payload_fields=["trace_id", "status"],
    ),
    "workflow.triaged": EventSchemaDefinition(
        event_type="workflow.triaged",
        schema_version="1.0.0",
        description="Triage classified the modality, region, and urgency.",
        required_payload_fields=["trace_id", "status", "modality", "region", "urgency"],
    ),
    "workflow.analysis_started": EventSchemaDefinition(
        event_type="workflow.analysis_started",
        schema_version="1.0.0",
        description="Specialist analysis began.",
        required_payload_fields=["trace_id", "status"],
    ),
    "workflow.retrieved": EventSchemaDefinition(
        event_type="workflow.retrieved",
        schema_version="1.0.0",
        description="Supporting evidence retrieval completed for the case context.",
        required_payload_fields=["trace_id", "status", "evidence_count", "modality"],
    ),
    "workflow.analysis_completed": EventSchemaDefinition(
        event_type="workflow.analysis_completed",
        schema_version="1.0.0",
        description="Specialist analysis produced draft findings.",
        required_payload_fields=["trace_id", "status", "findings"],
    ),
    "workflow.degraded": EventSchemaDefinition(
        event_type="workflow.degraded",
        schema_version="1.0.0",
        description="Case entered degraded mode due to failed or unavailable analysis.",
        required_payload_fields=["trace_id", "status"],
    ),
    "workflow.verification_completed": EventSchemaDefinition(
        event_type="workflow.verification_completed",
        schema_version="1.0.0",
        description="Verification finished for the current finding set.",
        required_payload_fields=["trace_id", "status", "flags", "escalated_findings"],
    ),
    "workflow.synthesized": EventSchemaDefinition(
        event_type="workflow.synthesized",
        schema_version="1.0.0",
        description="Differential and report draft were synthesized.",
        required_payload_fields=["trace_id", "status", "differential"],
    ),
    "workflow.calibrated": EventSchemaDefinition(
        event_type="workflow.calibrated",
        schema_version="1.0.0",
        description="Calibration and escalation decision completed.",
        required_payload_fields=["trace_id", "status", "required", "reason"],
    ),
    "workflow.awaiting_review": EventSchemaDefinition(
        event_type="workflow.awaiting_review",
        schema_version="1.0.0",
        description="Case is ready for clinician review.",
        required_payload_fields=["trace_id", "status"],
    ),
    "case.review.confirm": EventSchemaDefinition(
        event_type="case.review.confirm",
        schema_version="1.0.0",
        description="A clinician confirmed the draft.",
        required_payload_fields=["trace_id"],
    ),
    "case.review.edit": EventSchemaDefinition(
        event_type="case.review.edit",
        schema_version="1.0.0",
        description="A clinician edited the draft before acceptance.",
        required_payload_fields=["trace_id"],
    ),
    "case.review.reject": EventSchemaDefinition(
        event_type="case.review.reject",
        schema_version="1.0.0",
        description="A clinician rejected the draft.",
        required_payload_fields=["trace_id"],
    ),
}


def get_event_schema(event_type: str) -> EventSchemaDefinition:
    return CASE_EVENT_SCHEMAS.get(
        event_type,
        EventSchemaDefinition(
            event_type=event_type,
            schema_version="1.0.0",
            description="Unregistered case event.",
            required_payload_fields=["trace_id"],
        ),
    )
