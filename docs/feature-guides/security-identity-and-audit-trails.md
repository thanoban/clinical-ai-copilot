# Security, Identity, and Audit Trails

## What this feature does

This feature set controls who can do what, keeps tenants separated, and records
what happened in a replayable audit trail.

The main implementation lives in:

- `packages/core/src/aegis_dx/api/app.py`
- `packages/core/src/aegis_dx/identity.py`
- `packages/core/src/aegis_dx/audit.py`
- `packages/core/src/aegis_dx/store.py`
- `packages/core/src/aegis_dx/postgres_store.py`
- `packages/core/src/aegis_dx/workflow.py`

## Identity today: a seam, not a full enterprise auth system

The current system uses header-based identity:

- `X-Actor-Id`
- `X-Actor-Role`
- `X-Tenant-Id`

This is intentionally not final hospital SSO. But it is also not just random
request parsing glued into every endpoint.

The code has been shaped into an `IdentityPort` seam so future identity systems
can replace the current one without redesigning the entire application.

That means the project already distinguishes:

- **how a principal is resolved**
- from **how the app uses that principal**

That is a strong design choice.

## Authentication versus authorization

The identity adapter handles two different jobs:

### Authentication-like behavior

It resolves a `Principal` from headers and rejects malformed identity context.

### Authorization behavior

It checks:

- whether the actor has one of the required roles
- whether the actor belongs to the tenant that owns the case

This separation is subtle but important. It avoids mixing “who are you?” and
“are you allowed?” into one blurry check.

## Role gating in the API

`require_roles(...)` in `api/app.py` wraps each endpoint.

Examples:

- case submission allows clinician, reviewer, admin
- case listing and case detail allow clinician/reviewer/admin/auditor
- audit-log access is narrower
- review action blocks auditor access

This mirrors real hospital or enterprise systems where read access and action
access are not the same privilege.

## Tenant isolation

The project is multi-tenant, so tenant scope is not a minor detail.

The critical rule is:

> a user from tenant A cannot access tenant B’s cases.

That is enforced in the runtime when a case is fetched for a principal.
The store also scopes tenant-specific queries like case listing and idempotency
lookup.

This matters because proper tenant isolation should exist below the UI layer.

## Why the audit log is separate from lifecycle events

The system records two kinds of history:

### Audit log

The audit log answers:

- who did something?
- what action did they take?
- in which tenant/case context?

### Lifecycle events

The lifecycle event stream answers:

- what workflow transitions happened?
- in what order?
- under which versioned event type?

These are related, but not identical.

This separation is good design because product users, auditors, and engineers
care about different types of traceability.

## Hash chaining

The audit log is append-only and hash-chained.

Each audit record stores:

- its own content
- the previous hash
- a newly computed entry hash

The hash is built from fields like:

- prior hash
- case id
- tenant id
- event type
- actor id
- timestamp
- serialized payload

This creates tamper-evidence.

It is not the same as a blockchain, and it does not magically solve every
compliance problem, but it does make silent alteration much harder.

That is exactly the kind of practical security control an enterprise system
benefits from.

## Why audit is implemented as a port

`StoreAuditAdapter` is small, but the idea is important.

The workflow emits audit events through `AuditPort` rather than talking
directly to a particular store implementation.

That means:

- the workflow owns the decision that an action is auditable
- the adapter/store owns how persistence happens

This keeps audit as a cross-cutting concern without hard-wiring one persistence
strategy into domain logic.

## Correlation IDs as operational trace glue

The middleware sets and propagates `X-Correlation-Id`.

This is not just observability polish. It connects:

- HTTP requests,
- workflow processing,
- audit payloads,
- and case events.

That makes it much easier to reconstruct the full story of a case across system
boundaries.

## SQLite and Postgres parity

Both SQLite and Postgres stores preserve:

- case persistence
- tenant-scoped queries
- idempotency registration
- audit log append/list behavior
- lifecycle event append/list behavior

This parity is educational because it shows the storage contract is stable even
when the underlying database technology changes.

## What to remember

This feature teaches an important product-engineering truth:

- security is not one auth library
- audit is not one log file
- multi-tenancy is not one header

In this repo, identity, authorization, tenant scope, traceability, and
tamper-evident logging are all part of the normal product flow.
