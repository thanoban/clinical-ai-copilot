# Clinician Dashboard and Human Review

## What this feature does

The clinician dashboard is the human-facing control surface for the system.
It is where the product stops being “a backend with AI components” and becomes a
reviewable diagnostic workflow for a person.

The main implementation lives in:

- `apps/web/src/App.tsx`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/types.ts`
- `apps/web/src/styles.css`
- `apps/web/src/App.test.tsx`

## Why this UI matters architecturally

The dashboard is not just presentation. It enforces the project’s central
safety and product rule:

> the system output is research-only until a clinician confirms, edits, or rejects it.

That means the frontend is responsible for making the human gate visible and
usable, but the backend is still responsible for enforcing the underlying state rules.

This combination is important:

- the UI expresses the human review workflow clearly
- the backend prevents invalid transitions

That is stronger than relying on the UI alone.

## How the frontend is wired to the backend

The frontend deliberately uses the current backend route shapes directly.

It calls:

- `GET /v1/cases`
- `GET /v1/cases/{id}`
- `GET /v1/cases/{id}/events`
- `GET /v1/cases/{id}/audit`
- `POST /v1/cases/{id}/review`
- `POST /v1/cases`
- `GET /v1/model-status`
- `POST /v1/segmentations/refine`

This is an important learning choice:
the dashboard is not hiding the backend contract behind an extra frontend-only
data layer.

That makes the UI easier to study because its behavior maps closely onto the API.

## Session configuration

The dashboard lets you set:

- API base URL
- actor id
- actor role
- tenant id

This is useful for development because the UI can simulate different role and
tenant contexts without needing a full SSO flow.

It also teaches how much of the product behavior depends on identity context.

## Case list

The case list is more than navigation.
It visualizes:

- current cases for the tenant
- status
- modality
- site
- recency

This reflects the backend’s tenant-scoped list behavior and gives the operator a
fast picture of work in progress.

## Case detail

The case detail page teaches the product’s diagnostic philosophy by what it shows:

- overview metadata
- escalation status
- draft summary
- artifact context
- findings
- verifier agreement and flags
- differential
- evidence snippets
- report links
- lifecycle timeline
- audit trail

This is important because the UI does not only show “the answer.”
It shows the evidence and trust signals around the answer.

That matches the product’s goal of transparent AI-assisted review rather than
opaque AI output.

## Review actions

The three review actions are:

- confirm
- edit
- reject

These map directly onto domain-level `HumanAction`.

The edit path is especially useful educationally because it shows the UI and
backend coordinating over a stricter rule:

- edit requires edited summary text

The frontend disables bad submissions for better UX, but the backend also
validates the rule so correctness does not depend on the browser.

## Why the disclaimer stays visible

The research-only disclaimer appears persistently because it is not treated as a
legal footnote. It is part of the product semantics.

That is a good design lesson:
when a rule is central to safe product behavior, it should be visible in the
main interaction flow, not buried in a documentation page.

## Audit and lifecycle visibility

The dashboard distinguishes lifecycle events from audit events just like the
backend does.

That helps different users learn different stories:

- lifecycle shows what the system did
- audit shows who acted

The UI also handles role restrictions properly by surfacing why an audit log may
not be available for the current actor role.

## New case submission from the dashboard

The dashboard is not read-only.
It can also submit cases by collecting:

- MIME type
- report text
- optional artifact URI
- optional site id

That makes it a complete vertical slice rather than a passive viewer.

It also makes local testing easier because you can exercise intake and review
from one screen.

## Frontend tests

The component tests are valuable because they pin the UI contract to the backend
behavior.

They cover:

- rendering of the detail view
- review submission for confirm/edit/reject
- role-based audit behavior
- case submission behavior

This is helpful when learning the repo because the tests show the intended user
flows in small, readable scenarios.

## What to remember

This feature teaches that the dashboard is part of the trust architecture.

It does not merely decorate the backend.
It exposes the case state, evidence, and review gate in a way that makes the
human role operationally real.
