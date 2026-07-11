from __future__ import annotations

import time

from aegis_dx.consensus import MAX_VERIFICATION_ROUNDS
from aegis_dx.domain import (
    ActorRole,
    ArtifactInput,
    CaseSubmissionRequest,
    EvidenceSnippet,
    Finding,
    Principal,
    VerificationResult,
)
from aegis_dx.ports import SpecialistPort, VerificationPort
from aegis_dx.specialists import SpecialistRegistry
from aegis_dx.store import SQLiteCaseStore
from aegis_dx.workflow import WorkflowRuntime


PRINCIPAL = Principal(actor_id="clinician-1", tenant_id="tenant-a", role=ActorRole.CLINICIAN)


class _FixedFindingSpecialist(SpecialistPort):
    modality = "chest_xray"

    def __init__(self) -> None:
        self.call_count = 0

    def analyze(self, artifact, triage) -> list[Finding]:
        self.call_count += 1
        return [
            Finding(
                claim="Possible right lower lobe pneumonia.",
                locus="right-lower-lung-zone",
                probability=0.8,
                source_agent="cxr-specialist",
                model_version="test-v1",
            )
        ]


class _DisagreeThenAgreeVerifier(VerificationPort):
    """Disagrees for the first `disagree_rounds` calls, then agrees - proves
    the loop actually re-runs analysis+verification and eventually converges,
    rather than either never looping or looping forever."""

    def __init__(self, disagree_rounds: int) -> None:
        self._disagree_rounds = disagree_rounds
        self.call_count = 0

    def verify(self, artifact, findings, evidence, triage) -> list[VerificationResult]:
        self.call_count += 1
        disagreeing = self.call_count <= self._disagree_rounds
        return [
            VerificationResult(
                claim=finding.claim,
                agreement_score=0.1 if disagreeing else 0.9,
                critic_flags=["independent_model_disagreement"] if disagreeing else [],
                requires_escalation=disagreeing,
            )
            for finding in findings
        ]


class _AlwaysDisagreeVerifier(VerificationPort):
    def __init__(self) -> None:
        self.call_count = 0

    def verify(self, artifact, findings, evidence, triage) -> list[VerificationResult]:
        self.call_count += 1
        return [
            VerificationResult(
                claim=finding.claim,
                agreement_score=0.1,
                critic_flags=["independent_model_disagreement"],
                requires_escalation=True,
            )
            for finding in findings
        ]


class _EmptyEvidenceRetrieval:
    def retrieve(self, artifact, triage) -> list[EvidenceSnippet]:
        return []


def _build_runtime(tmp_path, verifier: VerificationPort, specialist: SpecialistPort) -> WorkflowRuntime:
    store = SQLiteCaseStore(tmp_path / "aegis_dx_loop_test.db")
    specialists = SpecialistRegistry([specialist])
    return WorkflowRuntime(
        store=store,
        specialists=specialists,
        retrieval=_EmptyEvidenceRetrieval(),
        verifier=verifier,
        worker_poll_interval_seconds=0.01,
    )


def _submit_and_wait(runtime: WorkflowRuntime, *, timeout_seconds: float = 5.0):
    case, _replayed = runtime.submit_case(
        CaseSubmissionRequest(artifact=ArtifactInput(mime_type="application/dicom", report_text="test")),
        PRINCIPAL,
    )
    runtime.start()
    try:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current = runtime.get_case(case.case_id, PRINCIPAL)
            if current.status.value in {"AwaitingReview", "Degraded"}:
                return current
            time.sleep(0.02)
        raise AssertionError("Case never reached a terminal-for-this-test status.")
    finally:
        runtime.stop()


def test_loop_reconverges_after_one_disagreement_round(tmp_path) -> None:
    verifier = _DisagreeThenAgreeVerifier(disagree_rounds=1)
    specialist = _FixedFindingSpecialist()
    runtime = _build_runtime(tmp_path, verifier, specialist)

    case = _submit_and_wait(runtime)

    assert case.verification_round == 1
    assert verifier.call_count == 2  # disagreed once, re-queried, agreed
    assert specialist.call_count == 2  # re-analyzed once as part of the re-query
    # consensus_kappa is legitimately None here: with a single finding and no
    # variance in either rater's call, Cohen's kappa is mathematically
    # undefined (p_e == 1.0) - see test_consensus.py for the kappa math itself.
    # This test's job is proving the loop actually re-queries and converges.

    events = runtime.list_case_events(case.case_id, PRINCIPAL)
    reverified = [event for event in events if event.event_type == "workflow.reverified"]
    assert len(reverified) == 1
    assert reverified[0].payload["verification_round"] == 1


def test_loop_is_bounded_and_surfaces_persistent_disagreement(tmp_path) -> None:
    verifier = _AlwaysDisagreeVerifier()
    specialist = _FixedFindingSpecialist()
    runtime = _build_runtime(tmp_path, verifier, specialist)

    case = _submit_and_wait(runtime)

    # Bounded: MAX_VERIFICATION_ROUNDS re-queries, never more.
    assert case.verification_round == MAX_VERIFICATION_ROUNDS
    assert verifier.call_count == MAX_VERIFICATION_ROUNDS + 1

    events = runtime.list_case_events(case.case_id, PRINCIPAL)
    reverified = [event for event in events if event.event_type == "workflow.reverified"]
    exhausted = [event for event in events if event.event_type == "workflow.verification_loop_exhausted"]
    assert len(reverified) == MAX_VERIFICATION_ROUNDS
    assert len(exhausted) == 1

    # Never hidden from the clinician - persistent disagreement must escalate.
    assert case.escalation.required is True


def test_loop_does_not_run_when_verifier_agrees_immediately(tmp_path) -> None:
    verifier = _DisagreeThenAgreeVerifier(disagree_rounds=0)
    specialist = _FixedFindingSpecialist()
    runtime = _build_runtime(tmp_path, verifier, specialist)

    case = _submit_and_wait(runtime)

    assert case.verification_round == 0
    assert verifier.call_count == 1
    assert specialist.call_count == 1

    events = runtime.list_case_events(case.case_id, PRINCIPAL)
    assert not [event for event in events if event.event_type == "workflow.reverified"]


def test_complexity_tier_is_recorded_on_every_case(tmp_path) -> None:
    verifier = _DisagreeThenAgreeVerifier(disagree_rounds=0)
    specialist = _FixedFindingSpecialist()
    runtime = _build_runtime(tmp_path, verifier, specialist)

    case = _submit_and_wait(runtime)

    assert case.complexity_tier in {"tier_1_fast", "tier_2_verified", "tier_3_panel"}

    events = runtime.list_case_events(case.case_id, PRINCIPAL)
    routed = [event for event in events if event.event_type == "workflow.complexity_routed"]
    assert len(routed) == 1
    assert routed[0].payload["complexity_tier"] == case.complexity_tier
