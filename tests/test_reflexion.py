from __future__ import annotations

from aegis_dx.composition import ReflexiveSynthesisAdapter
from aegis_dx.domain import DifferentialItem, EvidenceSnippet, Finding, TriageDecision, UrgencyLevel
from aegis_dx.ports import SynthesisPort


TRIAGE = TriageDecision(modality="chest_xray", region="thorax", urgency=UrgencyLevel.ROUTINE)


def _finding(probability: float = 0.8) -> Finding:
    return Finding(
        claim="Possible right lower lobe pneumonia.",
        locus="right-lower-lung-zone",
        probability=probability,
        source_agent="cxr-specialist",
        model_version="test-v1",
    )


class _FixedSynthesisAdapter(SynthesisPort):
    """Test double that always returns the same (possibly ungrounded) differential."""

    def __init__(self, differential: list[DifferentialItem]) -> None:
        self._differential = differential

    def synthesize(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[DifferentialItem]:
        return list(self._differential)


def test_reflexion_passes_through_a_well_grounded_differential_without_revising() -> None:
    finding = _finding()
    grounded = [
        DifferentialItem(
            diagnosis="right lower lobe pneumonia",
            confidence=0.7,
            rationale=f"Derived from cxr-specialist finding at {finding.locus}.",
        )
    ]
    adapter = ReflexiveSynthesisAdapter(_FixedSynthesisAdapter(grounded))

    result = adapter.synthesize([finding], [], TRIAGE)

    assert result == grounded
    assert adapter.last_revisions == 0
    assert adapter.last_incomplete is False


def test_reflexion_repairs_an_ungrounded_rationale() -> None:
    finding = _finding()
    ungrounded = [
        DifferentialItem(
            diagnosis="right lower lobe pneumonia",
            confidence=0.7,
            rationale="This looks like pneumonia.",  # no locus/source_agent citation
        )
    ]
    adapter = ReflexiveSynthesisAdapter(_FixedSynthesisAdapter(ungrounded))

    result = adapter.synthesize([finding], [], TRIAGE)

    assert result[0].rationale != "This looks like pneumonia."
    assert finding.locus in result[0].rationale
    assert adapter.last_revisions >= 1


def test_reflexion_clamps_overconfident_differential_to_the_strongest_finding() -> None:
    finding = _finding(probability=0.5)
    overconfident = [
        DifferentialItem(
            diagnosis="right lower lobe pneumonia",
            confidence=0.99,  # far exceeds the one supporting finding's 0.5 probability
            rationale=f"Grounded at {finding.locus}.",
        )
    ]
    adapter = ReflexiveSynthesisAdapter(_FixedSynthesisAdapter(overconfident))

    result = adapter.synthesize([finding], [], TRIAGE)

    assert result[0].confidence <= 0.5
    assert adapter.last_revisions >= 1


def test_reflexion_loop_is_bounded_and_flags_incomplete_on_persistent_failure() -> None:
    finding = _finding()

    class _AlwaysEmptyAdapter(SynthesisPort):
        """A double that never produces a differential at all - unlike an
        ungrounded rationale, an empty list survives `_revise`'s repair pass
        unchanged (there's nothing to append grounding text to), so this is a
        genuinely unfixable failure that must hit the round bound rather than
        self-correcting."""

        def synthesize(self, findings, evidence, triage) -> list[DifferentialItem]:
            return []

    adapter = ReflexiveSynthesisAdapter(_AlwaysEmptyAdapter(), max_revisions=2)

    result = adapter.synthesize([finding], [], TRIAGE)

    assert result == []
    assert adapter.last_revisions == 2  # hit the bound, did not loop forever
    assert adapter.last_incomplete is True  # never suppressed - the caller can see it failed


def test_reflexion_handles_empty_findings_without_revising() -> None:
    adapter = ReflexiveSynthesisAdapter(_FixedSynthesisAdapter([]))

    result = adapter.synthesize([], [], TRIAGE)

    assert result == []
    assert adapter.last_revisions == 0
    assert adapter.last_incomplete is False
