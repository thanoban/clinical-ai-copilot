// Mirrors packages/core/src/aegis_dx/domain.py exactly. Keep in sync by hand
// until a shared schema generator exists (docs/11's "typed contracts
// end-to-end" principle - this file is the seam until then).

export type CaseStatus =
  | "Received"
  | "DeIdentified"
  | "Triaged"
  | "Analyzing"
  | "Verifying"
  | "Synthesized"
  | "Calibrated"
  | "Escalated"
  | "Degraded"
  | "AwaitingReview"
  | "Confirmed"
  | "Edited"
  | "Rejected"
  | "Closed";

export type ActorRole = "clinician" | "reviewer" | "admin" | "auditor" | "service";

export type UrgencyLevel = "routine" | "urgent" | "stat";

export type HumanAction = "confirm" | "edit" | "reject";

export const TERMINAL_CASE_STATUSES: ReadonlySet<CaseStatus> = new Set([
  "Confirmed",
  "Edited",
  "Rejected",
  "Closed",
]);

export interface ArtifactRecord {
  mime_type: string;
  report_text: string | null;
  artifact_uri: string | null;
  source_system: string;
  de_identified: boolean;
  de_identified_text: string | null;
}

export interface Finding {
  claim: string;
  locus: string;
  probability: number;
  source_agent: string;
  model_version: string;
  saliency_ref: string | null;
}

export interface EvidenceSnippet {
  source_id: string;
  title: string;
  snippet: string;
  source_type: string;
  uri: string | null;
}

export interface VerificationResult {
  claim: string;
  agreement_score: number;
  critic_flags: string[];
  requires_escalation: boolean;
}

export interface DifferentialItem {
  diagnosis: string;
  confidence: number;
  rationale: string;
}

export interface EscalationDecision {
  required: boolean;
  reason: string | null;
}

export interface StructuredReport {
  summary: string;
  findings: string[];
  evidence_links: string[];
  disclaimer: string;
}

export interface HumanReviewRecord {
  action: HumanAction;
  actor_id: string;
  acted_at: string;
  note: string | null;
  edited_summary: string | null;
}

export interface CaseRecord {
  case_id: string;
  trace_id: string;
  tenant_id: string;
  site_id: string | null;
  status: CaseStatus;
  artifact: ArtifactRecord;
  modality: string | null;
  region: string | null;
  urgency: UrgencyLevel;
  evidence: EvidenceSnippet[];
  findings: Finding[];
  verification: VerificationResult[];
  differential: DifferentialItem[];
  escalation: EscalationDecision;
  report: StructuredReport | null;
  human_review: HumanReviewRecord | null;
  created_at: string;
  updated_at: string;
}

export interface CaseSubmissionAccepted {
  case_id: string;
  trace_id: string;
  status: CaseStatus;
  idempotency_replayed: boolean;
}

export interface CaseReviewRequest {
  action: HumanAction;
  note?: string;
  edited_summary?: string;
}

export interface AuditEvent {
  sequence: number | null;
  case_id: string;
  tenant_id: string;
  event_type: string;
  actor_id: string;
  actor_role: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  previous_hash: string | null;
  entry_hash: string | null;
}

export interface CaseLifecycleEvent {
  sequence: number | null;
  case_id: string;
  tenant_id: string;
  event_type: string;
  schema_version: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface EventSchemaDefinition {
  event_type: string;
  schema_version: string;
  description: string;
  required_payload_fields: string[];
}

export interface SessionConfig {
  apiBaseUrl: string;
  actorId: string;
  actorRole: ActorRole;
  tenantId: string;
}
