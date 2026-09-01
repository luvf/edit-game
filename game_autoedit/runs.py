"""Reading back what a training run produced."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import torch

from game_autoedit.datasets.dataset import DatasetSpec
from game_autoedit.datasets.targets import TargetSpec
from game_autoedit.datasets.windows import SamplingSpec, WindowSpec
from game_autoedit.models.tcn import BackboneSpec, ModelSpec, build_model

if TYPE_CHECKING:
    from pathlib import Path

    from torch import nn


class RunNotFoundError(FileNotFoundError):
    """Raised when a run directory holds no usable checkpoint."""


def _dataset_spec(payload: dict[str, Any]) -> DatasetSpec:
    """Rebuild the dataset spec stored in a run's config."""
    raw = payload.get("dataset", {})
    window = WindowSpec(**raw.get("window", {}))
    sampling = SamplingSpec(**raw.get("sampling", {}))
    target_raw = dict(raw.get("target", {}))
    target = TargetSpec(**target_raw)
    return DatasetSpec(
        window=window,
        sampling=sampling,
        target=target,
        sample_rate=int(raw.get("sample_rate", DatasetSpec().sample_rate)),
    )


def _model_spec(payload: dict[str, Any]) -> ModelSpec:
    """Rebuild the model spec stored in a run's config."""
    raw = payload.get("model", {})
    backbone_raw = dict(raw.get("backbone", {}))
    for key in ("downsample", "dilations"):
        if key in backbone_raw:
            backbone_raw[key] = tuple(backbone_raw[key])
    return ModelSpec(
        backbone=BackboneSpec(**backbone_raw),
        frontend=raw.get("frontend", "logmel"),
    )


@dataclass
class LoadedRun:
    """A trained run, ready to predict.

    `encoder` names the frozen encoder when the run trained a head on cached
    embeddings; it is None for the end-to-end model, which reads waveforms.
    """

    model: nn.Module
    payload: dict[str, Any]
    encoder: str | None
    dataset: DatasetSpec | None = None
    receptive_field: int = 1024

    @property
    def on_embeddings(self) -> bool:
        """Tell whether this run predicts from cached embeddings."""
        return self.encoder is not None


def _read_checkpoint(run_dir: Path, device: torch.device) -> dict[str, Any]:
    """Load a run's checkpoint and its stored configuration.

    Raises:
        RunNotFoundError: if the checkpoint is missing.
    """
    checkpoint_path = run_dir / "best.pt"
    if not checkpoint_path.exists():
        raise RunNotFoundError(f"aucun checkpoint dans {run_dir}")

    checkpoint: dict[str, Any] = torch.load(
        checkpoint_path, map_location=device, weights_only=False
    )
    if not checkpoint.get("run") and (run_dir / "run.json").exists():
        checkpoint["run"] = json.loads((run_dir / "run.json").read_text())
    return checkpoint


def load_run(run_dir: Path, device: torch.device) -> LoadedRun:
    """Load a trained model, whichever of the two paths produced it.

    Args:
        run_dir: the run directory holding ``best.pt``.
        device: where to place the model.

    Returns:
        The model in eval mode plus what is needed to feed it.
    """
    checkpoint = _read_checkpoint(run_dir, device)
    payload = checkpoint.get("run", {})
    encoder = payload.get("encoder")

    if encoder:
        from game_autoedit.models.head import EmbeddingTagger, HeadSpec

        raw = dict(payload.get("model", {}))
        if "dilations" in raw:
            raw["dilations"] = tuple(raw["dilations"])
        head = HeadSpec(**raw)
        input_dim = checkpoint["model"]["project.weight"].shape[1]
        model: nn.Module = EmbeddingTagger(int(input_dim), head).to(device)
        model.load_state_dict(checkpoint["model"])
        model.eval()
        return LoadedRun(
            model=model,
            payload=payload,
            encoder=str(encoder),
            receptive_field=head.receptive_field(),
        )

    dataset_spec = _dataset_spec(payload)
    waveform_model = build_model(_model_spec(payload)).to(device)
    waveform_model.load_state_dict(checkpoint["model"])
    waveform_model.eval()
    # Inference always walks the game end to end, whatever the run trained on.
    dataset_spec = replace(
        dataset_spec, sampling=replace(dataset_spec.sampling, strategy="dense")
    )
    return LoadedRun(
        model=waveform_model, payload=payload, encoder=None, dataset=dataset_spec
    )


def resolve_device(name: str | None) -> torch.device:
    """Return the device to run on, defaulting to CUDA when available."""
    if name:
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")
