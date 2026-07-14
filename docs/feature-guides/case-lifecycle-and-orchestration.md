# Case Lifecycle and Orchestration

## What this feature does

This feature is the backbone of the entire product. It takes a submitted case,
pushes it through a staged diagnostic workflow, records what happened, and
stops only when the case is ready for human review.

The main implementation lives in:

- `packages/core/src/aegis_dx/workflow.py`
- `packages/core/src/aegis_dx/api/app.py`
- `packages/core/src/aegis_dx/queueing.py`
- `packages/core/src/aegis_dx/store.py`
- `packages/core/src/aegis_dx/postgres_store.py`

## Why a workflow exists at all

In a simple CRUD app, a request comes in, some logic runs, and a response goes
back out. This project cannot stay simple like that because:

- model calls can be slow
- several steps happen in sequence
- some steps may fail independently
- a worker may need to continue after the HTTP request is already finished
- the clinician must see a persistent case record later

So the system uses a **state machine** rather than a one-shot request handler.

## The lifecycle states

The implemented state progression is:

- `Received`
- `DeIdentified`
- `Triaged`
- `Analyzing`
- `Verifying`
- `Synthesized`
- `Calibrated`
- `Escalated` or `Degraded`
- `AwaitingReview`
- `Confirmed`, `Edited`, or `Rejected`

This matters because each status is not just a label. It marks:

- what has already happened,
- what data should exist on the case,
- and what the next valid transition is.

That is why `review_case()` refuses review unless the case is in
`AwaitingReview`.

## Intake: from API request to persistent case

`POST /v1/cases` in `api/app.py` is intentionally thin.
It authenticates the principal, reads `Idempotency-Key` if present, and calls
`runtime.submit_case(...)`.

Inside `submit_case()`:

1. The runtime checks whether the same tenant already submitted the same
   idempotency key.
2. If yes, it returns the existing case and marks the response as replayed.
3. If no, it creates a fresh `CaseRecord`.
4. The artifact is normalized by the ingestion adapter.
5. The case is saved immediately.
6. Audit and lifecycle events are written immediately.
7. The case id is queued for background processing.

This is a classic asynchronous pattern:
accept fast, persist early, process later.

## Why idempotency matters

Medical or enterprise clients may retry requests because of:

- unstable networks,
- frontend refreshes,
- timeouts,
- or operational uncertainty about whether submission already succeeded.

Without idempotency, a retry could create duplicate cases. The project avoids
that by scoping the idempotency key to the tenant and looking up previously
submitted cases before creating a new one.

That is not just convenience. It is correctness.

## The worker loop

The worker loop is implemented inside `WorkflowRuntime.start()`,
`_run_worker()`, and `_process_case()`.

The runtime starts a background thread that repeatedly:

- dequeues a case id,
- processes the case according to its current status,
- acknowledges the queue item afterward.

This is intentionally small and explicit. Instead of hiding workflow behavior in
a framework engine, the code shows the control flow directly.

That makes it easier to learn.

## Why the queue is abstracted

Queueing is hidden behind `CaseQueuePort`.

Two implementations exist:

- `InProcessCaseQueue`
- `RedisStreamCaseQueue`

The first is cheap and easy for tests/dev.  
The second is deployment-shaped and supports separate API and worker processes
with at-least-once delivery.

This abstraction teaches an important lesson:
the orchestration logic should not care whether its queue is local memory or a
real durable broker.

## Retrieval before analysis

The workflow retrieves evidence before specialist analysis completes.
That means the case record accumulates:

- de-identified artifact context,
- triage context,
- and supporting evidence

before the system tries to finalize interpretation.

Architecturally, this is important because the project treats evidence as a
first-class citizen, not an afterthought added only to the final UI.

## Degraded paths are a feature, not a failure to design

The `Degraded` path exists because production-shaped systems must fail
transparently.

If:

- no specialist is registered,
- a specialist returns no findings,
- or analysis cannot produce a confident output,

the case does not disappear and the system does not pretend everything is fine.
Instead, it:

- marks the case degraded,
- builds a direct-review report,
- records the reason,
- and still routes the case to `AwaitingReview`.

That is an implementation of a safety principle:
**surface uncertainty, do not silently hide it.**

## Why the workflow saves so often

You will notice repeated calls to save case state and emit events.
This is deliberate.

Each meaningful transition:

- updates the case record,
- appends an audit event,
- appends a lifecycle event.

This creates replayable operational history and reduces the size of “lost work”
if something crashes mid-case.

The system does not yet do ultra-fine checkpointing, but it does save after
major state changes so recovery is good enough for the current maturity level.

## Completion is not model completion

The workflow marks technical completion when the case is ready for human review,
not when the model produced findings.

That distinction is central to the product philosophy:

- the AI pipeline can finish,
- but the case is not clinically finalized,
- until a human confirms, edits, or rejects it.

That is why the human review stage is represented in the same domain lifecycle,
not treated as a separate UI-only concept.

## What to remember

This feature teaches the project’s most important engineering move:

- **submission is asynchronous**
- **state is persistent**
- **processing is staged**
- **failure is explicit**
- **human review is part of the workflow, not outside it**
