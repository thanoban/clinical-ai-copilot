import type {
  AuditEvent,
  CaseLifecycleEvent,
  CaseRecord,
  CaseReviewRequest,
  CaseSubmissionAccepted,
  EventSchemaDefinition,
  SessionConfig,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function identityHeaders(config: SessionConfig): HeadersInit {
  return {
    "X-Actor-Id": config.actorId,
    "X-Actor-Role": config.actorRole,
    "X-Tenant-Id": config.tenantId,
  };
}

async function request<T>(path: string, config: SessionConfig, init?: RequestInit): Promise<T> {
  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...identityHeaders(config),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Response body wasn't JSON - fall back to the status text above.
    }
    throw new ApiError(detail || `Request to ${path} failed`, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listCases(config: SessionConfig): Promise<CaseRecord[]> {
  return request<CaseRecord[]>("/v1/cases", config);
}

export function getCase(caseId: string, config: SessionConfig): Promise<CaseRecord> {
  return request<CaseRecord>(`/v1/cases/${encodeURIComponent(caseId)}`, config);
}

export function submitCase(
  payload: { artifact: { mime_type: string; report_text?: string; source_system?: string }; site_id?: string },
  config: SessionConfig,
  idempotencyKey?: string,
): Promise<CaseSubmissionAccepted> {
  return request<CaseSubmissionAccepted>("/v1/cases", config, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function reviewCase(
  caseId: string,
  review: CaseReviewRequest,
  config: SessionConfig,
): Promise<CaseRecord> {
  return request<CaseRecord>(`/v1/cases/${encodeURIComponent(caseId)}/review`, config, {
    method: "POST",
    body: JSON.stringify(review),
  });
}

export function getAuditLog(caseId: string, config: SessionConfig): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/v1/cases/${encodeURIComponent(caseId)}/audit`, config);
}

export function getCaseEvents(caseId: string, config: SessionConfig): Promise<CaseLifecycleEvent[]> {
  return request<CaseLifecycleEvent[]>(`/v1/cases/${encodeURIComponent(caseId)}/events`, config);
}

export function getEventSchemas(config: SessionConfig): Promise<EventSchemaDefinition[]> {
  return request<EventSchemaDefinition[]>("/v1/event-schemas", config);
}
