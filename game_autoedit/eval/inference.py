"""Running the model over a whole game.

Training sees 30-second windows; a cut file needs the whole game. Windows are
walked with overlap and blended with a triangular weight, so a boundary that
lands near the edge of one window is still decided by the window where it sits
in the middle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch

from game_autoedit.data.audio import read_window
from game_autoedit.datasets.targets import CHANNELS
from game_autoedit.datasets.windows import dense_starts

if TYPE_CHECKING:
    from pathlib import Path

    from torch import nn

    from game_autoedit.datasets.dataset import DatasetSpec


def _blend_weights(steps: int) -> np.ndarray:
    """Return a triangular weight over a window, peaking in the middle."""
    ramp = np.minimum(np.arange(steps), np.arange(steps)[::-1]).astype(np.float64)
    peak = ramp.max()
    if peak <= 0:
        return np.ones(steps, dtype=np.float64)
    # The floor keeps the very first and last step from carrying zero weight.
    weights: np.ndarray = ramp / peak + 1e-3
    return weights


@torch.no_grad()
def predict_game(
    model: nn.Module,
    audio_path: Path,
    *,
    duration: float,
    spec: DatasetSpec,
    device: torch.device,
    batch_size: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Predict the three channel probabilities over a full game.

    Args:
        model: a trained tagger, already on `device`.
        audio_path: the cached 16 kHz audio.
        duration: the game duration in seconds.
        spec: the dataset spec the model was trained with; its window and hop
            define the grid.
        device: where to run.
        batch_size: windows per forward pass.

    Returns:
        ``(steps, 3)`` probabilities and the ``(steps,)`` centre times.
    """
    model.eval()
    total_steps = spec.target.steps_for(duration)
    times = spec.target.centers(0.0, total_steps)

    accumulator = np.zeros((total_steps, len(CHANNELS)), dtype=np.float64)
    weights = np.zeros((total_steps, 1), dtype=np.float64)

    window_steps = spec.steps_per_window()
    blend = _blend_weights(window_steps)[:, None]
    starts = dense_starts(duration, spec.window)

    for batch_start in range(0, len(starts), batch_size):
        batch = starts[batch_start : batch_start + batch_size]
        waveforms = np.stack(
            [
                read_window(
                    audio_path,
                    start,
                    spec.window.duration,
                    sample_rate=spec.sample_rate,
                )
                for start in batch
            ]
        )
        tensor = torch.from_numpy(waveforms).to(device)
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            logits = model(tensor, steps=window_steps)
        probabilities = torch.sigmoid(logits.float()).cpu().numpy()

        for offset, start in enumerate(batch):
            first = int(round(start / spec.target.hop))
            last = min(first + window_steps, total_steps)
            span = last - first
            if span <= 0:
                continue
            accumulator[first:last] += probabilities[offset, :span] * blend[:span]
            weights[first:last] += blend[:span]

    weights[weights == 0.0] = 1.0
    return (accumulator / weights).astype(np.float32), times
