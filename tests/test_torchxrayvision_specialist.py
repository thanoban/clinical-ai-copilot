from __future__ import annotations

from pathlib import Path

import pytest

from aegis_dx.domain import ArtifactRecord, TriageDecision, UrgencyLevel
from aegis_dx.models.torchxrayvision_backend import TorchXRayVisionUnavailable
from aegis_dx.specialists import HFTorchXRayVisionSpecialistAdapter, _resolve_local_image_path


TRIAGE = TriageDecision(modality="chest_xray", region="thorax", urgency=UrgencyLevel.ROUTINE)


class FakeClassifier:
    def __init__(self, probabilities: dict[str, float] | None = None, error: Exception | None = None) -> None:
        self._probabilities = probabilities or {}
        self._error = error
        self.classified_paths: list[str] = []

    def classify_image_path(self, image_path: str) -> dict[str, float]:
        if self._error:
            raise self._error
        self.classified_paths.append(image_path)
        return self._probabilities


def _artifact(artifact_uri: str | None) -> ArtifactRecord:
    return ArtifactRecord(mime_type="application/dicom", de_identified=True, artifact_uri=artifact_uri)


def test_resolve_local_image_path_accepts_plain_and_file_uri(tmp_path: Path) -> None:
    image_file = tmp_path / "scan.png"
    image_file.write_bytes(b"not-a-real-image-just-bytes")

    assert _resolve_local_image_path(str(image_file)) == str(image_file)

    resolved_from_uri = _resolve_local_image_path(image_file.as_uri())
    assert resolved_from_uri is not None
    assert Path(resolved_from_uri).samefile(image_file)


def test_resolve_local_image_path_rejects_missing_or_remote(tmp_path: Path) -> None:
    assert _resolve_local_image_path(None) is None
    assert _resolve_local_image_path(str(tmp_path / "does-not-exist.png")) is None
    assert _resolve_local_image_path("https://example.test/scan.png") is None


def test_falls_back_to_stub_when_no_image_is_available() -> None:
    adapter = HFTorchXRayVisionSpecialistAdapter(classifier=FakeClassifier())

    findings = adapter.analyze(_artifact(None), TRIAGE)

    assert findings
    assert findings[0].model_version == "stub-medgemma-cxr-v1"


def test_falls_back_to_stub_when_classifier_unavailable(tmp_path: Path) -> None:
    image_file = tmp_path / "scan.png"
    image_file.write_bytes(b"fake-bytes")
    adapter = HFTorchXRayVisionSpecialistAdapter(
        classifier=FakeClassifier(error=TorchXRayVisionUnavailable("no weights")),
    )

    findings = adapter.analyze(_artifact(str(image_file)), TRIAGE)

    assert findings
    assert findings[0].model_version == "stub-medgemma-cxr-v1"


def test_produces_findings_for_pathologies_above_threshold(tmp_path: Path) -> None:
    image_file = tmp_path / "scan.png"
    image_file.write_bytes(b"fake-bytes")
    classifier = FakeClassifier(
        probabilities={
            "Effusion": 0.91,
            "Cardiomegaly": 0.72,
            "Pneumonia": 0.2,
            "Fracture": 0.05,
        }
    )
    adapter = HFTorchXRayVisionSpecialistAdapter(classifier=classifier, positive_threshold=0.5)

    findings = adapter.analyze(_artifact(str(image_file)), TRIAGE)

    assert classifier.classified_paths == [str(image_file)]
    assert len(findings) == 2
    assert findings[0].claim == "Possible pleural effusion."
    assert findings[0].probability == 0.91
    assert findings[0].locus == "costophrenic-angle"
    assert findings[0].model_version == "torchxrayvision-densenet121-chex"
    assert findings[1].claim == "Possible cardiomegaly."


def test_reports_no_abnormality_when_nothing_crosses_threshold(tmp_path: Path) -> None:
    image_file = tmp_path / "scan.png"
    image_file.write_bytes(b"fake-bytes")
    classifier = FakeClassifier(probabilities={"Pneumonia": 0.1, "Fracture": 0.05})
    adapter = HFTorchXRayVisionSpecialistAdapter(classifier=classifier, positive_threshold=0.5)

    findings = adapter.analyze(_artifact(str(image_file)), TRIAGE)

    assert len(findings) == 1
    assert "No focal cardiopulmonary abnormality" in findings[0].claim
    assert findings[0].model_version == "torchxrayvision-densenet121-chex"


def test_caps_findings_at_max_findings(tmp_path: Path) -> None:
    image_file = tmp_path / "scan.png"
    image_file.write_bytes(b"fake-bytes")
    classifier = FakeClassifier(
        probabilities={name: 0.9 for name in ["Effusion", "Cardiomegaly", "Pneumonia", "Fracture", "Edema", "Atelectasis"]}
    )
    adapter = HFTorchXRayVisionSpecialistAdapter(classifier=classifier, positive_threshold=0.5, max_findings=3)

    findings = adapter.analyze(_artifact(str(image_file)), TRIAGE)

    assert len(findings) == 3


# --- Real-model integration test: exercises the actual downloaded weights ---


def _torchxrayvision_importable() -> bool:
    try:
        import torchxrayvision  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _torchxrayvision_importable(), reason="torchxrayvision is not installed (pip install -e '.[imaging]').")
def test_real_torchxrayvision_classifier_runs_end_to_end(tmp_path: Path) -> None:
    import numpy as np

    try:
        import skimage.io
    except ImportError:
        pytest.skip("scikit-image is not installed alongside torchxrayvision.")

    from aegis_dx.models.torchxrayvision_backend import TorchXRayVisionClassifier

    rng = np.random.default_rng(42)
    synthetic_image = (rng.random((256, 256)) * 255).astype("uint8")
    image_path = tmp_path / "synthetic.png"
    skimage.io.imsave(str(image_path), synthetic_image)

    classifier = TorchXRayVisionClassifier()
    try:
        probabilities = classifier.classify_image_path(str(image_path))
    except TorchXRayVisionUnavailable as exc:
        pytest.skip(f"torchxrayvision weights could not be loaded: {exc}")

    assert probabilities
    assert all(isinstance(value, float) for value in probabilities.values())
    assert all(0.0 <= value <= 1.0 for value in probabilities.values())
    assert "Cardiomegaly" in probabilities

    adapter = HFTorchXRayVisionSpecialistAdapter(classifier=classifier)
    findings = adapter.analyze(_artifact(str(image_path)), TRIAGE)
    assert findings
    assert all(0.0 <= finding.probability <= 1.0 for finding in findings)
