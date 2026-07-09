import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError, getAuditLog, getCase, getCaseEvents, listCases, reviewCase, submitCase } from "./lib/api";
import { formatDate, formatPercent, isTerminalStatus } from "./lib/format";
import type { AuditEvent, CaseLifecycleEvent, CaseRecord, HumanAction, SessionConfig } from "./lib/types";

const DEFAULT_CONFIG: SessionConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  actorId: import.meta.env.VITE_ACTOR_ID ?? "clinician-dashboard",
  actorRole: (import.meta.env.VITE_ACTOR_ROLE as SessionConfig["actorRole"]) ?? "clinician",
  tenantId: import.meta.env.VITE_TENANT_ID ?? "tenant-a",
};

const RESEARCH_ONLY_LABEL =
  "Research prototype only. Draft output must be confirmed, edited, or rejected by a licensed clinician.";

function sortByUpdatedAt(cases: CaseRecord[]): CaseRecord[] {
  return [...cases].sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime());
}

function isExternalLink(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function CaseLink({ href }: { href: string }) {
  return (
    <a className="resource-link" href={href} target={isExternalLink(href) ? "_blank" : undefined} rel={isExternalLink(href) ? "noreferrer" : undefined}>
      {href}
    </a>
  );
}

export function App() {
  const [config, setConfig] = useState<SessionConfig>(DEFAULT_CONFIG);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<CaseRecord | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[] | null>(null);
  const [auditUnavailableReason, setAuditUnavailableReason] = useState<string | null>(null);
  const [caseEvents, setCaseEvents] = useState<CaseLifecycleEvent[]>([]);
  const [casesLoading, setCasesLoading] = useState(true);
  const [caseLoading, setCaseLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [action, setAction] = useState<HumanAction>("confirm");
  const [note, setNote] = useState("");
  const [editedSummary, setEditedSummary] = useState("");
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "done">("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [newCaseMimeType, setNewCaseMimeType] = useState("application/dicom");
  const [newCaseReportText, setNewCaseReportText] = useState("");
  const [newCaseSiteId, setNewCaseSiteId] = useState("");
  const [newCaseState, setNewCaseState] = useState<"idle" | "submitting" | "done">("idle");
  const [newCaseError, setNewCaseError] = useState<string | null>(null);

  async function loadCases() {
    setCasesLoading(true);
    setError(null);
    try {
      const nextCases = sortByUpdatedAt(await listCases(config));
      setCases(nextCases);
      setSelectedCaseId((current) => current ?? nextCases[0]?.case_id ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load cases.");
    } finally {
      setCasesLoading(false);
    }
  }

  useEffect(() => {
    void loadCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    if (!selectedCaseId) {
      setSelectedCase(null);
      setAuditEvents(null);
      setAuditUnavailableReason(null);
      setCaseEvents([]);
      return;
    }

    let active = true;
    setCaseLoading(true);
    setError(null);

    void (async () => {
      try {
        const payload = await getCase(selectedCaseId, config);
        if (!active) return;
        setSelectedCase(payload);
        setAction(payload.human_review?.action ?? "confirm");
        setNote(payload.human_review?.note ?? "");
        setEditedSummary(payload.human_review?.edited_summary ?? payload.report?.summary ?? "");

        void getCaseEvents(selectedCaseId, config)
          .then((events) => active && setCaseEvents(events))
          .catch(() => active && setCaseEvents([]));

        try {
          const audit = await getAuditLog(selectedCaseId, config);
          if (active) {
            setAuditEvents(audit);
            setAuditUnavailableReason(null);
          }
        } catch (auditError) {
          if (!active) return;
          setAuditEvents(null);
          setAuditUnavailableReason(
            auditError instanceof ApiError && auditError.status === 403
              ? "Your role cannot view the audit log (reviewer, admin, or auditor only)."
              : "Audit log could not be loaded.",
          );
        }
      } catch (loadError) {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "Failed to load case details.");
      } finally {
        if (active) setCaseLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [selectedCaseId, config]);

  const selectedCaseReviewLocked = useMemo(() => {
    if (!selectedCase) return true;
    return isTerminalStatus(selectedCase.status) || selectedCase.status !== "AwaitingReview";
  }, [selectedCase]);

  async function handleReviewSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedCase) return;

    setSubmitState("submitting");
    setSubmitError(null);
    try {
      const updatedCase = await reviewCase(
        selectedCase.case_id,
        {
          action,
          note: note.trim() || undefined,
          edited_summary: action === "edit" ? editedSummary.trim() || undefined : undefined,
        },
        config,
      );
      setSelectedCase(updatedCase);
      setCases((current) => sortByUpdatedAt(current.map((entry) => (entry.case_id === updatedCase.case_id ? updatedCase : entry))));
      setSubmitState("done");
    } catch (reviewError) {
      setSubmitError(reviewError instanceof Error ? reviewError.message : "Review submission failed.");
      setSubmitState("idle");
    }
  }

  async function handleNewCaseSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNewCaseState("submitting");
    setNewCaseError(null);
    try {
      const accepted = await submitCase(
        {
          artifact: {
            mime_type: newCaseMimeType,
            report_text: newCaseReportText.trim() || undefined,
            source_system: "clinician-dashboard",
          },
          site_id: newCaseSiteId.trim() || undefined,
        },
        config,
      );
      setNewCaseState("done");
      setNewCaseReportText("");
      await loadCases();
      setSelectedCaseId(accepted.case_id);
    } catch (submitErr) {
      setNewCaseError(submitErr instanceof Error ? submitErr.message : "Case submission failed.");
      setNewCaseState("idle");
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-panel">
          <p className="eyebrow">Aegis-Dx</p>
          <h1>Clinician Dashboard</h1>
          <p className="lede">
            Review evidence-linked draft assessments and explicitly confirm, edit, or reject every case before it can
            be treated as clinician-approved.
          </p>
        </div>

        <section className="notice notice-warning" aria-label="research-only disclaimer">
          <strong>Research-only disclaimer</strong>
          <p>{RESEARCH_ONLY_LABEL}</p>
        </section>

        <section className="config-panel">
          <div className="section-heading">
            <h2>Session</h2>
            <button type="button" className="ghost-button" onClick={() => void loadCases()}>
              Refresh
            </button>
          </div>
          <label>
            API base URL
            <input
              value={config.apiBaseUrl}
              placeholder="(same origin / dev proxy)"
              onChange={(event) => setConfig((current) => ({ ...current, apiBaseUrl: event.target.value }))}
            />
          </label>
          <label>
            Actor ID
            <input value={config.actorId} onChange={(event) => setConfig((current) => ({ ...current, actorId: event.target.value }))} />
          </label>
          <label>
            Actor role
            <select
              value={config.actorRole}
              onChange={(event) => setConfig((current) => ({ ...current, actorRole: event.target.value as SessionConfig["actorRole"] }))}
            >
              <option value="clinician">clinician</option>
              <option value="reviewer">reviewer</option>
              <option value="admin">admin</option>
              <option value="auditor">auditor</option>
            </select>
          </label>
          <label>
            Tenant ID
            <input value={config.tenantId} onChange={(event) => setConfig((current) => ({ ...current, tenantId: event.target.value }))} />
          </label>
        </section>

        <section className="cases-panel">
          <div className="section-heading">
            <h2>Cases</h2>
            <span className="metric">{cases.length}</span>
          </div>
          {casesLoading ? <p className="muted">Loading cases…</p> : null}
          {!casesLoading && cases.length === 0 ? <p className="muted">No cases returned for this tenant yet.</p> : null}
          <div className="case-list" role="list">
            {cases.map((entry) => (
              <button
                key={entry.case_id}
                type="button"
                className={`case-row ${selectedCaseId === entry.case_id ? "selected" : ""}`}
                onClick={() => setSelectedCaseId(entry.case_id)}
              >
                <div>
                  <strong>{entry.modality ?? "Untriaged case"}</strong>
                  <p>{entry.site_id ?? "Unknown site"}</p>
                </div>
                <div className="case-meta">
                  <span className={`status-chip status-${entry.status.toLowerCase()}`}>{entry.status}</span>
                  <span>{formatDate(entry.updated_at)}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="submit-panel">
          <h2>Submit new case</h2>
          <form onSubmit={(event) => void handleNewCaseSubmit(event)}>
            <label>
              MIME type
              <select value={newCaseMimeType} onChange={(event) => setNewCaseMimeType(event.target.value)}>
                <option value="application/dicom">application/dicom (chest X-ray)</option>
                <option value="application/ecg">application/ecg</option>
              </select>
            </label>
            <label>
              Report text
              <textarea
                rows={3}
                value={newCaseReportText}
                onChange={(event) => setNewCaseReportText(event.target.value)}
                placeholder="e.g. Possible pneumonia in the right lower lobe."
              />
            </label>
            <label>
              Site ID (optional)
              <input value={newCaseSiteId} onChange={(event) => setNewCaseSiteId(event.target.value)} />
            </label>
            {newCaseError ? <div className="notice notice-error">{newCaseError}</div> : null}
            {newCaseState === "done" ? <div className="notice notice-ok">Case submitted.</div> : null}
            <button type="submit" className="primary-button" disabled={newCaseState === "submitting"}>
              {newCaseState === "submitting" ? "Submitting…" : "Submit case"}
            </button>
          </form>
        </section>
      </aside>

      <main className="content">
        <header className="content-header">
          <div>
            <p className="eyebrow">Human-in-the-loop review</p>
            <h2>Case detail</h2>
          </div>
          {selectedCase ? (
            <div className="trace-box">
              <span>Trace</span>
              <code>{selectedCase.trace_id}</code>
            </div>
          ) : null}
        </header>

        {error ? <section className="notice notice-error">{error}</section> : null}
        {caseLoading ? <section className="card">Loading case details…</section> : null}
        {!caseLoading && !selectedCase ? (
          <section className="card">Select a case from the left, or submit a new one, to view findings and review it.</section>
        ) : null}

        {!caseLoading && selectedCase ? (
          <div className="content-grid">
            <section className="card stack">
              <div className="section-heading">
                <h3>Overview</h3>
                <span className={`status-chip ${selectedCase.escalation.required ? "status-escalated" : ""}`}>{selectedCase.status}</span>
              </div>
              <dl className="summary-grid">
                <div>
                  <dt>Case ID</dt>
                  <dd>{selectedCase.case_id}</dd>
                </div>
                <div>
                  <dt>Site</dt>
                  <dd>{selectedCase.site_id ?? "Unknown"}</dd>
                </div>
                <div>
                  <dt>Modality</dt>
                  <dd>{selectedCase.modality ?? "Pending triage"}</dd>
                </div>
                <div>
                  <dt>Region</dt>
                  <dd>{selectedCase.region ?? "Unknown"}</dd>
                </div>
                <div>
                  <dt>Urgency</dt>
                  <dd>{selectedCase.urgency}</dd>
                </div>
                <div>
                  <dt>Updated</dt>
                  <dd>{formatDate(selectedCase.updated_at)}</dd>
                </div>
              </dl>

              <div className={`notice ${selectedCase.escalation.required ? "notice-warning" : "notice-ok"}`}>
                <strong>{selectedCase.escalation.required ? "Escalation required" : "No active escalation"}</strong>
                <p>{selectedCase.escalation.reason ?? "Verifier and guardrail checks did not require escalation."}</p>
              </div>

              <div className="report-box">
                <h3>Draft summary</h3>
                <p>{selectedCase.report?.summary ?? "No summary available yet."}</p>
                <p className="disclaimer-text">{selectedCase.report?.disclaimer ?? RESEARCH_ONLY_LABEL}</p>
              </div>

              <div className="artifact-box">
                <h3>Artifact context</h3>
                <dl className="artifact-grid">
                  <div>
                    <dt>MIME type</dt>
                    <dd>{selectedCase.artifact.mime_type}</dd>
                  </div>
                  <div>
                    <dt>Source system</dt>
                    <dd>{selectedCase.artifact.source_system}</dd>
                  </div>
                  <div>
                    <dt>De-identified</dt>
                    <dd>{selectedCase.artifact.de_identified ? "Yes" : "No"}</dd>
                  </div>
                  <div>
                    <dt>Tenant</dt>
                    <dd>{selectedCase.tenant_id}</dd>
                  </div>
                </dl>
                <p className="muted">
                  {selectedCase.artifact.de_identified_text ?? selectedCase.artifact.report_text ?? "No source text was provided for this case."}
                </p>
              </div>
            </section>

            <section className="card stack">
              <h3>Findings</h3>
              {selectedCase.findings.length === 0 ? <p className="muted">No findings returned.</p> : null}
              {selectedCase.findings.map((finding) => {
                const verification = selectedCase.verification.find((entry) => entry.claim === finding.claim);
                return (
                  <article key={finding.claim} className="finding-card">
                    <div className="section-heading">
                      <strong>{finding.claim}</strong>
                      <span>{formatPercent(finding.probability)}</span>
                    </div>
                    <p className="muted">
                      Locus: <code>{finding.locus}</code>
                    </p>
                    <p className="muted">
                      Source: {finding.source_agent} · {finding.model_version}
                    </p>
                    {finding.saliency_ref ? (
                      <p className="muted">
                        Saliency reference: <code>{finding.saliency_ref}</code>
                      </p>
                    ) : null}
                    {verification ? (
                      <div className="verification-box">
                        <span>Verifier agreement {formatPercent(verification.agreement_score)}</span>
                        <span>{verification.requires_escalation ? "Escalation recommended" : "No verifier escalation"}</span>
                        {verification.critic_flags.length > 0 ? <p>Flags: {verification.critic_flags.join(", ")}</p> : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}

              <h3>Differential</h3>
              {selectedCase.differential.length === 0 ? <p className="muted">No differential suggestions were produced.</p> : null}
              {selectedCase.differential.map((item) => (
                <article key={`${item.diagnosis}-${item.confidence}`} className="finding-card">
                  <div className="section-heading">
                    <strong>{item.diagnosis}</strong>
                    <span>{formatPercent(item.confidence)}</span>
                  </div>
                  <p>{item.rationale}</p>
                </article>
              ))}
            </section>

            <section className="card stack">
              <h3>Evidence</h3>
              {selectedCase.evidence.length === 0 ? <p className="muted">No evidence snippets available.</p> : null}
              {selectedCase.evidence.map((item) => (
                <article key={item.source_id} className="evidence-card">
                  <div className="section-heading">
                    <strong>{item.title}</strong>
                    <span className="pill">{item.source_type}</span>
                  </div>
                  <p>{item.snippet}</p>
                  <p className="muted">Source ID: {item.source_id}</p>
                  {item.uri ? (
                    <p className="muted">
                      Evidence link: <CaseLink href={item.uri} />
                    </p>
                  ) : null}
                </article>
              ))}

              <h3>Report links</h3>
              {selectedCase.report?.evidence_links?.length ? (
                <ul className="link-list">
                  {selectedCase.report.evidence_links.map((link) => (
                    <li key={link}>
                      <CaseLink href={link} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No report links were provided.</p>
              )}

              <h3>Case timeline</h3>
              {caseEvents.length === 0 ? (
                <p className="muted">No lifecycle events recorded yet.</p>
              ) : (
                <ul className="timeline-list">
                  {caseEvents.map((event) => (
                    <li key={`${event.event_type}-${event.sequence}`}>
                      <span className="timeline-type">{event.event_type}</span>
                      <span className="muted">{formatDate(event.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}

              <h3>Audit trail</h3>
              {auditUnavailableReason ? <p className="muted">{auditUnavailableReason}</p> : null}
              {!auditUnavailableReason && auditEvents && auditEvents.length === 0 ? (
                <p className="muted">No audit events recorded yet.</p>
              ) : null}
              {!auditUnavailableReason && auditEvents && auditEvents.length > 0 ? (
                <ul className="timeline-list">
                  {auditEvents.map((event) => (
                    <li key={`${event.event_type}-${event.sequence}`}>
                      <span className="timeline-type">{event.event_type}</span>
                      <span className="muted">
                        {event.actor_id} · {formatDate(event.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section className="card stack">
              <div className="section-heading">
                <h3>Clinician action</h3>
                {selectedCase.human_review ? (
                  <span className="pill">
                    {selectedCase.human_review.action} by {selectedCase.human_review.actor_id}
                  </span>
                ) : null}
              </div>
              <p className="muted">Every draft remains research-only until a licensed clinician confirms, edits, or rejects it.</p>

              {selectedCase.human_review ? (
                <div className="notice">
                  <strong>Recorded review</strong>
                  <p>
                    {selectedCase.human_review.action} by {selectedCase.human_review.actor_id} on{" "}
                    {formatDate(selectedCase.human_review.acted_at)}
                  </p>
                  {selectedCase.human_review.note ? <p>{selectedCase.human_review.note}</p> : null}
                </div>
              ) : null}

              <form className="review-form" onSubmit={(event) => void handleReviewSubmit(event)}>
                <fieldset disabled={selectedCaseReviewLocked || submitState === "submitting"}>
                  <legend>Select action</legend>
                  <label className="radio-row">
                    <input type="radio" name="action" checked={action === "confirm"} onChange={() => setAction("confirm")} />
                    Confirm draft
                  </label>
                  <label className="radio-row">
                    <input type="radio" name="action" checked={action === "edit"} onChange={() => setAction("edit")} />
                    Edit then accept
                  </label>
                  <label className="radio-row">
                    <input type="radio" name="action" checked={action === "reject"} onChange={() => setAction("reject")} />
                    Reject draft
                  </label>

                  <label>
                    Review note
                    <textarea
                      rows={4}
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      placeholder="Document why you confirmed, edited, or rejected this draft."
                    />
                  </label>

                  <label>
                    Edited summary
                    <textarea
                      rows={5}
                      value={editedSummary}
                      onChange={(event) => setEditedSummary(event.target.value)}
                      placeholder="Required when choosing edit."
                    />
                  </label>
                </fieldset>

                {selectedCaseReviewLocked ? (
                  <div className="notice">
                    This case is already in <strong>{selectedCase.status}</strong> and cannot be reviewed again from this screen.
                  </div>
                ) : null}
                {submitError ? <div className="notice notice-error">{submitError}</div> : null}
                {submitState === "done" ? <div className="notice notice-ok">Review action saved successfully.</div> : null}

                <button
                  type="submit"
                  className="primary-button"
                  disabled={selectedCaseReviewLocked || submitState === "submitting" || (action === "edit" && editedSummary.trim().length === 0)}
                >
                  {submitState === "submitting" ? "Submitting…" : "Submit review action"}
                </button>
              </form>
            </section>
          </div>
        ) : null}
      </main>
    </div>
  );
}
