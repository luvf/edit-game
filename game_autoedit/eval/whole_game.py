"""Running the head over an entire game in a single pass.

The head is fully convolutional, so a two-hour game goes through it exactly as
a training window does. Nothing is chopped, so no prediction is ever made on a
truncated context and no blending is needed to hide the seams — which is what
the sliding-window inference over raw audio had to do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch

from game_autoedit.datasets.targets import CHANNELS

if TYPE_CHECKING:
    from torch import nn

    from game_autoedit.data.embeddings import EmbeddingStore

# Above this many steps the game is cut into overlapping slabs, purely to bound
# memory; the overlap is wider than the receptive field so the result is
# identical to a single pass.
MAX_STEPS = 40_000


@torch.no_grad()
def predict_whole_game(
    model: nn.Module,
    store: EmbeddingStore,
    game_id: int,
    device: torch.device,
    *,
    receptive_field: int = 1024,
) -> tuple[np.ndarray, np.ndarray]:
    """Predict the three channel probabilities over a whole game.

    Args:
        model: the trained head, already on `device`.
        store: the embedding cache.
        game_id: which game to run.
        device: where to run.
        receptive_field: the head's span in steps, used to size the overlap
            when a game has to be processed in slabs.

    Returns:
        ``(steps, 3)`` probabilities and the ``(steps,)`` centre times.
    """
    model.eval()
    embeddings = np.asarray(store.load(game_id), dtype=np.float32)
    total = embeddings.shape[0]
    times = (np.arange(total, dtype=np.float64) + 0.5) * store.hop

    if total <= MAX_STEPS:
        tensor = torch.from_numpy(embeddings).unsqueeze(0).to(device)
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            logits = model(tensor)
        return torch.sigmoid(logits.float())[0].cpu().numpy(), times

    margin = max(receptive_field, 1)
    stride = MAX_STEPS - 2 * margin
    output = np.zeros((total, len(CHANNELS)), dtype=np.float32)
    for start in range(0, total, stride):
        first = max(start - margin, 0)
        last = min(start + stride + margin, total)
        slab = torch.from_numpy(embeddings[first:last]).unsqueeze(0).to(device)
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            logits = model(slab)
        probabilities = torch.sigmoid(logits.float())[0].cpu().numpy()
        keep_from = start - first
        keep_to = min(start + stride, total) - first
        output[start : start + (keep_to - keep_from)] = probabilities[keep_from:keep_to]
    return output, times
