# 11 — Engineering Practices & Delivery

What makes a codebase "professional" is not the framework list — it's the
discipline around change. For a system heading toward medical-device territory, this
also maps to **IEC 62304** (software lifecycle) and is worth doing well from the start.

## Test strategy — the pyramid, with contract tests as the keystone

```
        /\      E2E — golden cases through the whole pipeline (few, high value)
       /--\     Integration — the graph with fake adapters (the verify loop, escalation)
      /----\    Contract — every adapter must satisfy its port's shared test suite  ★
     /------\   Unit — domain logic (routing, fusion, calibration) with ports mocked
```

- **Unit** — pure domain logic (orchestration decisions, differential fusion,
  calibration math) with all ports mocked. Fast, run on every commit.
- **★ Contract tests — the professional payoff of hexagonal design.** Each port ships
  a **shared contract test suite**; every adapter (`cxr_medgemma_adapter`,
  `brain_nnunet_adapter`, …) must pass the *same* `SpecialistPort` contract. This is
  what actually guarantees the [D3](07-risks-decisions.md) promise that "adding
  vertical #2 doesn't touch the orchestrator" — a new adapter is done when it passes
  the contract, and the graph is guaranteed to accept it.
- The walking skeleton already applies this pattern to ingestion, triage, and the
  first stub CXR specialist adapter, so future verticals extend an existing contract
  surface instead of inventing one.
- The same contract-first pattern now also covers retrieval, synthesis, and report
  adapters, which keeps Phase-3 workflow evolution testable without depending on a
  live vector store or external LLM.
- The trust layer now follows the same rule: verification and guardrail adapters
  have shared contracts, so escalation behavior can evolve without turning the
  workflow into an untestable tangle of conditional logic.
- **Integration** — the LangGraph graph wired with fake/deterministic adapters, so the
  verify loop, escalation paths, and the `Degraded`/`Failed` transitions are tested
  without GPUs or LLM cost.
- **E2E** — a small set of **golden cases** (known CXR + report → expected findings +
  escalation behavior) run against a staging deployment. Guards the whole flow.
- **Model eval** — the `eval/` suite (κ, calibration, subgroup, selective-prediction)
  runs as a **CI gate** on model/prompt changes ([10](10-observability-mlops.md)).
- **Load** — Phase-4 load test establishes the throughput numbers behind the SLOs
  in [08](08-scalability-architecture.md).

## CI/CD

**CI (every PR):**
- Lint + format (ruff/black; eslint/prettier).
- **Type-check** (mypy/pyright strict; TypeScript strict) — non-negotiable for a
  system this size.
- Unit + contract + integration tests.
- Security scans: **SAST**, dependency/vulnerability scan, **container image scan**.
- Model eval gate when models/prompts change.

**CD (GitOps):**
- Build → **sign** images → push to registry.
- Promote through environments; **canary/shadow** for model changes ([10](10-observability-mlops.md)).
- Infrastructure as Code (**Terraform**) + Helm/Kustomize manifests; no click-ops in prod.
- Database migrations versioned and run as part of deploy.

## Environments

| Env | Data | Purpose |
|-----|------|---------|
| **dev** | Synthetic / fully-open only — **never PHI** | Fast iteration |
| **staging** | De-identified / open data | Integration, E2E golden cases, load tests |
| **prod** | Real (per tenant, PHI-safe) | Live clinical *research* use, human-in-loop |

PHI never touches dev. Staging mirrors prod topology so performance and config bugs
surface before prod.

## API & contract conventions

- **OpenAPI-first** for the HTTP API; the async intake returns `202 + case id`, and
  results are delivered via SSE/WebSocket or a `GET /cases/{id}` poll.
- **Idempotent intake** — clients may send `Idempotency-Key` on `POST /v1/cases`; the
  API replays the original accepted case instead of creating duplicates.
- **Semantic versioning** for the API; version in the path (`/v1/`). Never break a
  released contract.
- **Event schema registry** — the case lifecycle events ([08](08-scalability-architecture.md))
  have versioned, documented schemas. Downstream (audit, data platform) depends on them.
  The walking skeleton exposes `/v1/event-schemas` plus `/v1/cases/{id}/events`.
- **Typed contracts end-to-end** — shared types between the domain, the API, and the
  Next.js frontend so a contract change is a compile error, not a runtime surprise.

## Definition of Done (per change)

- [ ] Code + tests (unit/contract/integration as applicable) green in CI.
- [ ] Type-check + lint + security scans pass.
- [ ] If a model/prompt/calibrator changed: eval gate passed, no subgroup regression.
- [ ] Observability wired (traces/metrics/logs for new paths) — [10](10-observability-mlops.md).
- [ ] Audit events emitted for new consequential actions — [09](09-security-identity-audit.md).
- [ ] Docs/ADR updated if a decision or contract changed.
- [ ] No PHI in logs, tests, or fixtures.

## Repository & collaboration

- Trunk-based or short-lived feature branches; PRs required; review before merge.
- Conventional commits; automated changelog.
- ADRs ([07](07-risks-decisions.md)) for any decision expensive to reverse.
- The `docs/` planning set is living documentation — update it in the same PR as the
  change it describes.

## Mapping to IEC 62304 (for the eventual SaMD path)

The practices above are not busywork — they are the evidence an auditor expects:
requirements traceability (ADRs + this doc set), verification (the test pyramid +
eval gates), configuration management (IaC + model registry + DVC), and problem
resolution (dead-letter queue + audit log + incident process). Doing them from day
one means the compliance path is *documentation of what you already do*, not a rewrite.
