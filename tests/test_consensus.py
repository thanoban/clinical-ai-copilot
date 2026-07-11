from __future__ import annotations

import pytest

from aegis_dx.consensus import (
    MAX_VERIFICATION_ROUNDS,
    TIER_1_FAST,
    TIER_2_VERIFIED,
    TIER_3_PANEL,
    classify_complexity_tier,
    cohens_kappa_from_binary_calls,
    compute_case_consensus,
    requires_requery,
)
from aegis_dx.domain import Finding, UrgencyLevel, VerificationResult


def _finding(claim: str, probability: float) -> Finding:
    return Finding(
        claim=claim,
        locus="test-locus",
        probability=probability,
        source_agent="test-specialist",
        model_version="test-v1",
    )


def _verification(claim: str, agreement_score: float, flags: list[str] | None = None) -> VerificationResult:
    return VerificationResult(
        claim=claim,
        agreement_score=agreement_score,
        critic_flags=flags or [],
        requires_escalation=False,
    )


def test_cohens_kappa_perfect_agreement_is_one() -> None:
    kappa = cohens_kappa_from_binary_calls([True, False, True, False], [True, False, True, False])
    assert kappa == 1.0


def test_cohens_kappa_perfect_disagreement_is_negative() -> None:
    kappa = cohens_kappa_from_binary_calls([True, True, False, False], [False, False, True, True])
    assert kappa is not None
    assert kappa < 0


def test_cohens_kappa_returns_none_for_mismatched_or_empty_input() -> None:
    assert cohens_kappa_from_binary_calls([], []) is None
    assert cohens_kappa_from_binary_calls([True], [True, False]) is None


def test_cohens_kappa_returns_none_when_expected_agreement_is_certain() -> None:
    # Both raters always say True -> p_e == 1.0 -> division undefined, not "perfect agreement".
    assert cohens_kappa_from_binary_calls([True, True, True], [True, True, True]) is None


def test_compute_case_consensus_matches_manual_kappa() -> None:
    findings = [_finding("a", 0.9), _finding("b", 0.2), _finding("c", 0.8), _finding("d", 0.1)]
    verification = [
        _verification("a", 0.9),
        _verification("b", 0.2),
        _verification("c", 0.2),  # specialist says positive, verifier disagrees
        _verification("d", 0.1),
    ]
    kappa = compute_case_consensus(findings, verification)
    expected = cohens_kappa_from_binary_calls([True, False, True, False], [True, False, False, False])
    assert kappa == expected


def test_compute_case_consensus_none_when_no_overlap() -> None:
    findings = [_finding("unmatched-claim", 0.9)]
    verification = [_verification("a-different-claim", 0.9)]
    assert compute_case_consensus(findings, verification) is None
    assert compute_case_consensus([], []) is None


def test_requires_requery_true_on_disagreement_flag() -> None:
    verification = [_verification("a", 0.9, flags=["independent_model_disagreement"])]
    assert requires_requery(kappa=0.9, verification=verification) is True


def test_requires_requery_true_on_low_kappa() -> None:
    assert requires_requery(kappa=0.1, verification=[]) is True


def test_requires_requery_false_on_strong_agreement() -> None:
    verification = [_verification("a", 0.9, flags=["independent_model_confirmation"])]
    assert requires_requery(kappa=0.9, verification=verification) is False


def test_requires_requery_false_when_kappa_is_none_and_no_flags() -> None:
    assert requires_requery(kappa=None, verification=[]) is False


@pytest.mark.parametrize(
    ("urgency", "findings", "verification", "kappa", "expected_tier"),
    [
        (UrgencyLevel.STAT, [_finding("a", 0.9)], [], 0.9, TIER_3_PANEL),
        (UrgencyLevel.ROUTINE, [], [], None, TIER_2_VERIFIED),
        (UrgencyLevel.ROUTINE, [_finding("a", 0.9)], [], 0.9, TIER_1_FAST),
        (UrgencyLevel.ROUTINE, [_finding("a", 0.4)], [], None, TIER_2_VERIFIED),
        (
            UrgencyLevel.ROUTINE,
            [_finding("a", 0.9)],
            [_verification("a", 0.2, flags=["independent_model_disagreement"])],
            None,
            TIER_2_VERIFIED,
        ),
        (
            UrgencyLevel.ROUTINE,
            [_finding("a", 0.3)],
            [_verification("a", 0.2, flags=["independent_model_disagreement"])],
            None,
            TIER_3_PANEL,
        ),
        (UrgencyLevel.ROUTINE, [_finding("a", 0.9)], [], 0.1, TIER_3_PANEL),
    ],
)
def test_classify_complexity_tier(urgency, findings, verification, kappa, expected_tier) -> None:
    assert classify_complexity_tier(findings, verification, urgency, kappa) == expected_tier


def test_max_verification_rounds_is_a_small_positive_bound() -> None:
    # Sanity check on the constant itself - the loop must be bounded, and
    # "bounded" has to mean a small number, not something effectively unlimited.
    assert 0 < MAX_VERIFICATION_ROUNDS <= 3
