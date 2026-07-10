from __future__ import annotations


DEFAULT_WEIGHTS = "densenet121-res224-chex"

# torchxrayvision's DenseNet121 pads its fixed pathology vector with empty
# strings for labels the CheXpert-trained weights don't predict - filtered
# out wherever this dict is consumed.
_LOCUS_BY_PATHOLOGY: dict[str, str] = {
    "Atelectasis": "lung-base",
    "Consolidation": "lung-parenchyma",
    "Pneumothorax": "pleural-space",
    "Edema": "bilateral-lung-fields",
    "Effusion": "costophrenic-angle",
    "Pneumonia": "lung-parenchyma",
    "Cardiomegaly": "cardiac-silhouette",
    "Lung Lesion": "lung-parenchyma",
    "Fracture": "bony-thorax",
    "Lung Opacity": "lung-parenchyma",
    "Enlarged Cardiomediastinum": "mediastinum",
}


class TorchXRayVisionUnavailable(Exception):
    """Raised when the torchxrayvision package or its weights can't be used."""


class TorchXRayVisionClassifier:
    """Thin, lazily-initialized wrapper around a real torchxrayvision model.

    Wraps `torchxrayvision.models.DenseNet(weights=...)` - an independently
    trained CheXpert/NIH classifier, genuinely separate from any LLM-based
    specialist, which is what makes it useful as a second, heterogeneous
    opinion (D6, docs/07-risks-decisions.md) once wired behind a port.
    """

    def __init__(self, weights: str = DEFAULT_WEIGHTS) -> None:
        self._weights = weights
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        try:
            import torchxrayvision as xrv
        except ImportError as exc:
            raise TorchXRayVisionUnavailable(
                "torchxrayvision is not installed - install the 'imaging' extra "
                "(pip install -e '.[imaging]') to use this classifier."
            ) from exc

        try:
            model = xrv.models.DenseNet(weights=self._weights)
        except Exception as exc:  # noqa: BLE001 - network/IO/corrupt-cache errors from the download step
            raise TorchXRayVisionUnavailable(
                f"Could not load torchxrayvision weights '{self._weights}'."
            ) from exc

        model.eval()
        self._model = model
        return model

    def classify_image_array(self, image) -> dict[str, float]:
        """Classify a single-channel (H, W) numpy array of pixel intensities.

        Returns a {pathology_name: probability} dict, with the empty-string
        padding labels already filtered out.
        """
        import numpy as np
        import torch
        import torchxrayvision as xrv

        model = self._ensure_loaded()

        normalized = xrv.datasets.normalize(np.asarray(image), 255)
        if normalized.ndim == 2:
            normalized = normalized[None, ...]
        cropped = xrv.datasets.XRayCenterCrop()(normalized)
        tensor = torch.from_numpy(cropped).unsqueeze(0).float()

        with torch.no_grad():
            output = model(tensor)

        probabilities = output[0].detach().cpu().numpy().tolist()
        return {
            name: float(prob)
            for name, prob in zip(model.pathologies, probabilities)
            if name
        }

    def classify_image_path(self, image_path: str) -> dict[str, float]:
        """Load a grayscale image from disk and classify it."""
        import skimage.io

        # skimage's as_gray=True only rescales to a [0, 1] float when it has
        # to convert from color (rgb2gray) - a source that's already
        # single-channel (the common case for X-rays) passes through
        # untouched in its native 0-255 range. Rescale only the former case,
        # or a genuinely grayscale image gets scaled twice.
        image = skimage.io.imread(image_path, as_gray=True)
        if image.dtype != "uint8" and image.max() <= 1.0:
            image = image * 255.0
        return self.classify_image_array(image)

    @staticmethod
    def locus_for_pathology(pathology: str) -> str:
        return _LOCUS_BY_PATHOLOGY.get(pathology, "global-thorax")
