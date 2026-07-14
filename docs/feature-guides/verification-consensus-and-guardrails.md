# Verification, Consensus, and Guardrails

## What this feature does

This feature is the system’s main trust layer.
It asks a second mechanism to challenge specialist findings, decides whether the
case is trustworthy enough to proceed, and escalates when disagreement or weak
support appears.

The main implementation lives in:

- `packages/core/src/aegis_dx/trust.py`
- `packages/core/src/aegis_dx/consensus.py`
- `packages/core/src/aegis_dx/composition.py`
- `packages/core/src/aegis_dx/workflow.py`

## Why the verifier exists

The product deliberately avoids “model says X, therefore X is accepted.”

Instead, it follows this pattern:

1. specialist produces findings
2. verifier critiques those findings
3. consensus and trust signals are computed
4. guardrails decide whether escalation is required
5. only then does the case move toward clinician review

This makes the system more like a maker-checker workflow than a single-model
assistant.

## The verifier implementations

### Stub verifier

`StubVerificationAdapter` is rule-based.
It checks things like:

- low specialist confidence
- missing supporting evidence
- tentative claim language

Then it converts that into:

- `agreement_score`
- `critic_flags`
- `requires_escalation`

This is deterministic, fast, and easy to reason about.

### Remote model-backed verifier

`ModelBackedVerificationAdapter` sends the artifact, findings, evidence, and
triage context to an external critic endpoint.

This is important conceptually:
the verifier is not supposed to be the same thing as the specialist.
It is a separate perspective.

### Local heterogeneous verifier

`HFTorchXRayVisionVerificationAdapter` uses a local pretrained model to check
whether the specialist’s claims align with another signal source.

It mixes:

- the fallback verifier’s flags
- local model probabilities
- disagreement and confirmation thresholds

This creates a more realistic notion of independent confirmation than the stub alone.

## The heterogeneous-verifier rule

One of the strongest design choices in the repo is
`assert_heterogeneous_verifier(...)`.

It refuses startup when:

- the specialist and verifier point to the same remote endpoint
- or both are configured to use the same local torchxrayvision backend

Why is this such an important rule?

Because “a model verified itself” is not true independent verification, even if
it looks good in logs or UI.

This is a subtle but serious systems-design lesson:
architectural separation is not enough if deployment configuration collapses it.

## Consensus and re-query

The project does not stop at one verification pass.

After verification, the workflow computes:

- a **consensus score** (`consensus_kappa`)
- whether re-query is needed
- and a **complexity tier**

If disagreement remains high enough, the workflow can loop back from
`VERIFYING` to `ANALYZING`.

That means the same case can get:

- another specialist analysis round
- another verification round

before moving forward.

This is one of the most “agentic” parts of the codebase, but it is still bounded
and explicit.

## Why the loop is bounded

The loop uses `MAX_VERIFICATION_ROUNDS`.

That matters because an unbounded disagreement loop would be dangerous:

- it could burn compute forever
- it could hide persistent uncertainty
- it could make the system appear smarter than it really is

Instead, the code says:

- retry a little
- record the retries
- if disagreement persists, surface it

This is a very healthy product rule.

## Guardrails

The verifier says whether findings are questionable.
The guardrail decides what operational consequence that should have.

`StubGuardrailAdapter` escalates on:

- `STAT` urgency
- missing supporting evidence
- escalation-required verification results

This means trust is not just a score. It becomes a workflow decision.

That distinction is important:

- verification produces analysis about trust
- guardrails produce product behavior from that analysis

## Reflexion in synthesis

The trust system is not limited to verifier checks.
The synthesis step is wrapped in a reflexive layer too.

`ReflexiveSynthesisAdapter` gives the differential a bounded chance to repair
itself when the generated rationale is not grounded enough.

So there are two types of self-correction in the project:

- **verification loop** between specialist and verifier
- **reflexion loop** inside synthesis

They solve different problems:

- the verifier loop checks whether claims are independently supportable
- the reflexion loop checks whether the fused output is well-grounded and not
  overconfident

## Complexity tiers

The workflow assigns a complexity tier after verification.
This is forward-looking architecture.

Even if a full consultation panel is not implemented yet, the code already
creates a place where future routing policy can decide:

- easy case -> simple path
- ambiguous case -> extra reasoning
- very hard case -> richer multi-agent consultation

So the current code is not only solving today’s problem; it is shaping where
tomorrow’s feature growth will plug in.

## What to remember

This feature teaches the trust philosophy of the project:

- do not trust a specialist blindly
- verify with a distinct mechanism
- retry only a little
- record disagreement explicitly
- turn trust signals into workflow behavior
- keep the human final authority intact
