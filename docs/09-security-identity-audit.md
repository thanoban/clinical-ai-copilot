# 09 — Security, Identity & Audit

[06 — Compliance & Safety](06-compliance-safety.md) covers the *regulatory/ethical*
posture (PHI policy, SaMD, human-in-loop). This doc covers the *technical security*
controls that enterprise hospital buyers and auditors will require. In healthcare,
these are entry tickets, not differentiators — but they're also a genuine moat once
built, because competitors underinvest here.

## Identity & access

- **AuthN — federated SSO.** Hospitals run their own identity providers; support
  **OIDC / SAML** (and SCIM for user provisioning). No local password store for
  clinical users. Service-to-service auth via mTLS or signed workload identity.
- **AuthZ — RBAC + attribute-based tenant scoping.** Roles map to real clinical
  responsibilities:

  | Role | Can |
  |------|-----|
  | Radiologist / Clinician | View assigned cases, confirm/edit/reject drafts |
  | Reviewer / Supervisor | All of the above + reassign, view escalations |
  | Admin | Manage users, per-tenant config, thresholds |
  | Auditor | Read-only access to audit log + reports; no case actions |
  | Service | Machine identities for workers (least privilege, per-tier) |

  Every permission is **scoped to a tenant/site** — a clinician at site A can never
  see site B's cases. Enforced at the data layer (row-level security), not just the UI.

- **Least privilege everywhere.** Workers get only the queues, buckets, and secrets
  their tier needs. No shared "god" service account.

## Immutable audit log (a hard requirement — build it in Phase 1)

Every consequential action is recorded to an **append-only, tamper-evident**
(hash-chained) log:

- Every AI output (which model version produced which finding, with what confidence).
- Every case view (who opened which case, when).
- Every human action (confirm / edit / reject + the diff of edits).
- Every config or threshold change; every model promotion/rollback.
- Every data access and export.

Properties: append-only, hash-chained (each entry references the prior hash),
exportable for external audit, PHI-scrubbed where the log itself crosses boundaries,
and retained per policy. This log is simultaneously a **compliance control**, a
**debugging tool**, and a **sales asset** ("full traceability of every AI-assisted
decision").

## Secrets & keys

- Secrets in a **managed vault** (HashiCorp Vault / cloud secrets manager) — never in
  env files, images, or git.
- Short-lived, rotated credentials; workload identity over static keys where possible.
- Per-tenant encryption keys for data isolation; envelope encryption for artifacts.

## Encryption

- **In transit:** TLS everywhere, including service-to-service inside the cluster.
- **At rest:** encrypted object store (artifacts), encrypted DB (case store, audit log).
- **Field-level** encryption for any residual quasi-identifiers that must persist.

## Network & the PHI boundary — the LLM egress rule

This is the single most important security correction to the original plan:

> **Only de-identified data may leave the PHI boundary.** The orchestrator, verifier,
> synthesis, and reporter agents call external LLM providers — so **de-identification
> must be complete and verified *before* any external call**, OR those calls must go
> to an **in-VPC / enterprise LLM deployment covered by a BAA** (Business Associate
> Agreement), OR use **self-hosted** models.

Concretely:

- PHI-touching services live in **private subnets** with no inbound internet and
  **controlled egress** (allow-list only).
- De-identification happens in the `IngestionPort` adapter, before triage — and is
  **verified** (see safety checklist in [06](06-compliance-safety.md)) on a sample.
- The **LLM gateway** is the single controlled egress point for model calls; it
  enforces "de-identified payloads only" and logs every external call for audit.
- Decision D11 (see [07](07-risks-decisions.md)) tracks the self-hosted-vs-enterprise-LLM
  choice — it has cost, latency, and compliance trade-offs and must be made before pilot.

## Threat model (STRIDE-lite highlights)

| Threat | Control |
|--------|---------|
| PHI exfiltration via LLM prompts | De-id-before-egress rule + LLM gateway allow-list + egress logging |
| Broken tenant isolation (cross-site data leak) | Row-level security + per-tenant keys + scoped tokens |
| Audit tampering | Hash-chained append-only log, write-once storage, separate access path |
| Model output relied on as clinical truth | Mandatory human-confirm gate + research-only framing |
| Compromised worker → lateral movement | Least-privilege service identities, network segmentation |
| Supply-chain (poisoned model/dependency) | Signed images, dependency + container scanning, pinned model registry ([10](10-observability-mlops.md)) |

## Compliance frameworks to design toward

Not required for the research MVP, but architecting toward them now shortens the
enterprise/regulatory path later and signals seriousness to buyers:

- **HIPAA** (US PHI), **GDPR** (EU personal data) — data handling, consent, right-to-erasure.
- **ISO/IEC 27001** — information security management.
- **IEC 62304** — medical device *software lifecycle* (maps to [11](11-engineering-practices.md)).
- **ISO 14971** — medical device risk management (maps to the risk register in [07](07-risks-decisions.md)).
- **ISO 13485** — quality management system (longer-term, for a cleared product).

MVP stance: implement the security *controls* (auth, audit, encryption, egress) for
real; treat the *certifications* as a documented target, not a Phase-1 deliverable.
