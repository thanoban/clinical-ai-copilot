"""Bounded-loop decision logic for docs/15-agentic-architecture.md.

Pure, deterministic functions - no model calls here. This module answers three
questions the workflow's verify<->re-query loop and complexity router need:

1. How much do the specialist and the verifier actually agree (`Cohen's kappa
   <https://en.wikipedia.org/wiki/Cohen%27s_kappa>`_, not "the agents stopped
   arguing")?
2. Given that agreement, does this case need another verification round
   (bounded, per D18)?
3. Given the specialist's calibrated confidence and the verifier's signal,
   which complexity tier does this case belong in (docs/15 SS4)?
"""

from __future__ import annotations

from aegis_dx.domain import Finding, UrgencyLevel, VerificationResult

# Bounds - "every loop is bounded and budgeted" (docs/15 SS3 principle 1).
MAX_VERIFICATION_ROUNDS = 2

# A finding is "confidently positive" to the specialist at this probability.
DEFAULT_SPECIALIST_THRESHOLD = 0.5
# A finding is "confirmed" by the verifier at this agreement score.
DEFAULT_VERIFIER_THRESHOLD = 0.6

# Below this kappa, agreement is no better than a coin flip adjusted for
# base rates - treat it as a real disagreement, not noise.
REQUERY_KAPPA_THRESHOLD = 0.4

# Tier boundaries for the complexity router (docs/15 SS4).
TIER_1_FAST = "tier_1_fast"
TIER_2_VERIFIED = "tier_2_verified"
TIER_3_PANEL = "tier_3_panel"

_DISAGREEMENT_FLAGS = frozenset(
    {
        "independent_model_disagreement",
        "severe_verifier_disagreement",
        "verifier_disagreement",
    }
)


def cohens_kappa_from_binary_calls(rater_a: list[bool], rater_b: list[bool]) -> float | None:
    """Cohen's kappa for two raters' binary calls over the same N items.

    kappa = (p_o - p_e) / (1 - p_e), where p_o is observed agreement and p_e
    is the agreement expected by chance given each rater's own positive rate.
    Returns None (not 0.0 or 1.0) when there is nothing to compare or when
    both raters are perfectly uniform (p_e == 1, division undefined) - callers
    must treat "no signal" as "no signal," never silently as full agreement.
    """
    if not rater_a or len(rater_a) != len(rater_b):
        return None

    n = len(rater_a)
    observed_agreement = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b) / n
    a_positive_rate = sum(rater_a) / n
    b_positive_rate = sum(rater_b) / n
    expected_agreement = (a_positive_rate * b_positive_rate) + (
        (1 - a_positive_rate) * (1 - b_positive_rate)
    )

    if expected_agreement >= 1.0:
        return None
    return round((observed_agreement - expected_agreement) / (1 - expected_agreement), 4)


def compute_case_consensus(
    findings: list[Finding],
    verification: list[VerificationResult],
    *,
    specialist_threshold: float = DEFAULT_SPECIALIST_THRESHOLD,
    verifier_threshold: float = DEFAULT_VERIFIER_THRESHOLD,
) -> float | None:
    """Cohen's kappa between the specialist's implied calls (probability >=
    threshold) and the verifier's implied calls (agreement_score >= threshold)
    across every finding in one case that both sides actually scored.
    """
    if not findings or not verification:
        return None

    verification_by_claim = {item.claim: item for item in verification}
    specialist_calls: list[bool] = []
    verifier_calls: list[bool] = []
    for finding in findings:
        result = verification_by_claim.get(finding.claim)
        if result is None:
            continue
        specialist_calls.append(finding.probability >= specialist_threshold)
        verifier_calls.append(result.agreement_score >= verifier_threshold)

    return cohens_kappa_from_binary_calls(specialist_calls, verifier_calls)


def requires_requery(
    kappa: float | None,
    verification: list[VerificationResult],
    *,
    kappa_threshold: float = REQUERY_KAPPA_THRESHOLD,
) -> bool:
    """Whether the verify<->re-query loop (docs/15 SS5.2) should run another round.

    True on an explicit disagreement flag from any verifier adapter, or on
    low measured kappa. The caller is responsible for the round-count bound -
    this function only answers "would another round help," not "is it allowed."
    """
    if any(_DISAGREEMENT_FLAGS.intersection(item.critic_flags) for item in verification):
        return True
    if kappa is not None and kappa < kappa_threshold:
        return True
    return False


def classify_complexity_tier(
    findings: list[Finding],
    verification: list[VerificationResult],
    urgency: UrgencyLevel,
    kappa: float | None,
) -> str:
    """Adaptive complexity router (docs/15 SS4) - driven by calibrated confidence
    and disagreement signals already present in the case state, not an LLM's
    self-assessment of its own difficulty.
    """
    if urgency == UrgencyLevel.STAT:
        return TIER_3_PANEL

    if not findings:
        return TIER_2_VERIFIED

    has_disagreement_flag = any(
        _DISAGREEMENT_FLAGS.intersection(item.critic_flags) for item in verification
    )
    min_probability = min(finding.probability for finding in findings)

    if kappa is not None and kappa < 0.2:
        return TIER_3_PANEL
    if has_disagreement_flag and min_probability < 0.5:
        return TIER_3_PANEL
    if has_disagreement_flag or (kappa is not None and kappa < 0.6):
        return TIER_2_VERIFIED
    if min_probability >= 0.75:
        return TIER_1_FAST
    return TIER_2_VERIFIED
