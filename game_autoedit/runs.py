"""Reading back what a training run produced."""

from __future__ import annotations

import json
from dataclasses import replace
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


def load_run(
    run_dir: Path, device: torch.device
) -> tuple[nn.Module, DatasetSpec, dict[str, Any]]:
    """Load a trained model and the specs it was trained with.

    Args:
        run_dir: the run directory holding ``best.pt``.
        device: where to place the model.

    Returns:
        The model in eval mode, its dataset spec, and the stored run config.

    Raises:
        RunNotFoundError: if the checkpoint is missing.
    """
    checkpoint_path = run_dir / "best.pt"
    if not checkpoint_path.exists():
        raise RunNotFoundError(f"aucun checkpoint dans {run_dir}")

    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    payload = checkpoint.get("run", {})
    if not payload and (run_dir / "run.json").exists():
        payload = json.loads((run_dir / "run.json").read_text())

    dataset_spec = _dataset_spec(payload)
    model = build_model(_model_spec(payload)).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    # Inference always walks the game end to end, whatever the run trained on.
    dataset_spec = replace(
        dataset_spec, sampling=replace(dataset_spec.sampling, strategy="dense")
    )
    return model, dataset_spec, payload


def resolve_device(name: str | None) -> torch.device:
    """Return the device to run on, defaulting to CUDA when available."""
    if name:
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")
