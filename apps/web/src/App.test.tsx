import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuditEvent, CaseRecord } from "./lib/types";

function makeCase(overrides: Partial<CaseRecord> = {}): CaseRecord {
  return {
    case_id: "case-1",
    trace_id: "trace-1",
    tenant_id: "tenant-a",
    site_id: "site-a",
    status: "AwaitingReview",
    artifact: {
      mime_type: "application/dicom",
      report_text: "Possible pneumonia in the right lower lobe.",
      artifact_uri: null,
      source_system: "unit-test",
      de_identified: true,
      de_identified_text: "Possible pneumonia in the right lower lobe.",
    },
    modality: "chest_xray",
    region: "thorax",
    urgency: "routine",
    evidence: [
      {
        source_id: "guideline-cxr-pneumonia",
        title: "CXR pneumonia follow-up guidance",
        snippet: "Correlate lower-lobe opacity with clinical findings.",
        source_type: "guideline",
        uri: "guideline://cxr/pneumonia",
      },
    ],
    findings: [
      {
        claim: "Possible right lower lobe pneumonia.",
        locus: "right-lower-lung-zone",
        probability: 0.76,
        source_agent: "cxr-specialist",
        model_version: "stub-medgemma-cxr-v1",
        saliency_ref: "overlay://right-lower-lung-zone",
      },
    ],
    verification: [
      {
        claim: "Possible right lower lobe pneumonia.",
        agreement_score: 0.8,
        critic_flags: [],
        requires_escalation: false,
      },
    ],
    differential: [
      {
        diagnosis: "right lower lobe pneumonia",
        confidence: 0.78,
        rationale: "Derived from cxr-specialist at right-lower-lung-zone.",
      },
    ],
    escalation: { required: false, reason: null },
    report: {
      summary: "Draft clinician review package prepared for chest_xray analysis with retrieved evidence support.",
      findings: ["Possible right lower lobe pneumonia. (confidence 0.76)"],
      evidence_links: ["guideline://cxr/pneumonia"],
      disclaimer: "Research prototype only. This draft is not for clinical use and must be confirmed, edited, or rejected by a licensed clinician.",
    },
    human_review: null,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:05:00Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("App", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the disclaimer, case list, and evidence-linked detail view", async () => {
    const testCase = makeCase();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.endsWith("/v1/cases")) return Promise.resolve(jsonResponse([testCase]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}`)) return Promise.resolve(jsonResponse(testCase));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/events`)) return Promise.resolve(jsonResponse([]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/audit`)) return Promise.resolve(jsonResponse([] satisfies AuditEvent[]));
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    expect(screen.getByText(/research prototype only/i)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Possible right lower lobe pneumonia.")).toBeInTheDocument());
    expect(screen.getByText("right lower lobe pneumonia")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /guideline:\/\/cxr\/pneumonia/ }).length).toBeGreaterThan(0);
  });

  it("disables the review form once a case is no longer AwaitingReview", async () => {
    const testCase = makeCase({ status: "Confirmed", human_review: { action: "confirm", actor_id: "clinician-1", acted_at: "2026-07-10T00:06:00Z", note: null, edited_summary: null } });
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.endsWith("/v1/cases")) return Promise.resolve(jsonResponse([testCase]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}`)) return Promise.resolve(jsonResponse(testCase));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/events`)) return Promise.resolve(jsonResponse([]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/audit`)) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    await waitFor(() => expect(screen.getByText(/cannot be reviewed again/)).toBeInTheDocument());
    const submitButton = screen.getByRole("button", { name: /submit review action/i });
    expect(submitButton).toBeDisabled();
  });

  it("submits a confirm review action to the current backend route", async () => {
    const testCase = makeCase();
    const confirmedCase = makeCase({
      status: "Confirmed",
      human_review: { action: "confirm", actor_id: "clinician-dashboard", acted_at: "2026-07-10T00:07:00Z", note: null, edited_summary: null },
    });

    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();
      if (url.endsWith("/v1/cases") && (!init || init.method === undefined)) return Promise.resolve(jsonResponse([testCase]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}`) && (!init || init.method === undefined)) return Promise.resolve(jsonResponse(testCase));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/events`)) return Promise.resolve(jsonResponse([]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/audit`)) return Promise.resolve(jsonResponse([]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/review`) && init?.method === "POST") {
        const body = JSON.parse(init.body as string);
        expect(body.action).toBe("confirm");
        return Promise.resolve(jsonResponse(confirmedCase));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: /submit review action/i })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /submit review action/i }));

    await waitFor(() => expect(screen.getByText(/review action saved successfully/i)).toBeInTheDocument());
  });

  it("requires an edited summary before allowing an edit action to submit", async () => {
    const testCase = makeCase();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.endsWith("/v1/cases")) return Promise.resolve(jsonResponse([testCase]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}`)) return Promise.resolve(jsonResponse(testCase));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/events`)) return Promise.resolve(jsonResponse([]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/audit`)) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByPlaceholderText(/required when choosing edit/i)).toBeInTheDocument());

    const editedSummaryField = screen.getByPlaceholderText(/required when choosing edit/i);
    await user.clear(editedSummaryField);
    await user.click(screen.getByRole("radio", { name: /edit then accept/i }));

    expect(screen.getByRole("button", { name: /submit review action/i })).toBeDisabled();
  });

  it("shows a role-specific message when the audit log is not authorized", async () => {
    const testCase = makeCase();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.endsWith("/v1/cases")) return Promise.resolve(jsonResponse([testCase]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}`)) return Promise.resolve(jsonResponse(testCase));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/events`)) return Promise.resolve(jsonResponse([]));
      if (url.endsWith(`/v1/cases/${testCase.case_id}/audit`)) return Promise.resolve(jsonResponse({ detail: "Role is not allowed to access this endpoint." }, 403));
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    await waitFor(() => expect(screen.getByText(/cannot view the audit log/i)).toBeInTheDocument());
  });

  it("submits a new case through the submission form", async () => {
    const acceptedCaseId = "case-new";
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();
      if (url.endsWith("/v1/cases") && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({ case_id: acceptedCaseId, trace_id: acceptedCaseId, status: "Received", idempotency_replayed: false }, 202),
        );
      }
      if (url.endsWith("/v1/cases")) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByText(/no cases returned/i)).toBeInTheDocument());

    const submitPanel = screen.getByText("Submit new case").closest("section");
    if (!submitPanel) throw new Error("Submit panel not found");
    await user.type(within(submitPanel).getByPlaceholderText(/possible pneumonia/i), "Possible pneumonia in the right lower lobe.");
    await user.click(within(submitPanel).getByRole("button", { name: /submit case/i }));

    await waitFor(() => expect(within(submitPanel).getByText(/case submitted/i)).toBeInTheDocument());
  });
});
