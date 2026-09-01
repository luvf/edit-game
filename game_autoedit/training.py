"""The training loop.

Kept deliberately plain: one file, no framework, so the parts that matter on
this problem — how windows are drawn and how the rare boundary steps are
weighted — stay visible instead of hiding behind a callback.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import torch
from torch import nn
from torch.amp.grad_scaler import GradScaler
from torch.utils.data import DataLoader

from game_autoedit.datasets.dataset import DatasetSpec
from game_autoedit.datasets.targets import CHANNEL_INDEX, CHANNELS
from game_autoedit.models.tcn import ModelSpec

if TYPE_CHECKING:
    from pathlib import Path

    from torch.utils.data import Dataset

    from game_autoedit.datasets.dataset import TargetRatesDataset

# A rare channel gets at most this much extra weight; past it the loss stops
# teaching the model and starts teaching it to guess.
MAX_POS_WEIGHT = 40.0

# A soft target at or above this counts as a positive step.
POSITIVE_LEVEL = 0.5

# Which channels decide the best checkpoint. The validation loss is dominated
# by the heavily weighted rare positives and starts diverging long before the
# boundary channels stop improving, so it is the wrong thing to select on.
SELECTION_CHANNELS = ("in", "out")


@dataclass(frozen=True)
class TrainSpec:
    """Optimisation settings.

    Attributes:
        epochs: passes over the resampled window index.
        batch_size: windows per step; 8 x 30 s fits an 8 GB card comfortably.
        learning_rate: peak learning rate of the cosine schedule.
        weight_decay: AdamW decay.
        warmup_fraction: share of the run spent ramping the learning rate up.
        patience: stop after this many epochs without a better selection
            score; 0 disables it.
        num_workers: dataloader workers; each one seeks in the cache.
        loss: ``bce`` weights the rare channels, ``focal`` down-weights the easy
            negatives instead.
        focal_gamma: focusing strength when `loss` is ``focal``.
        channel_weights: relative importance of the three channels in the loss.
        amp: mixed precision, roughly twice as fast on the card at hand.
        seed: makes a run reproducible.
    """

    epochs: int = 30
    batch_size: int = 8
    patience: int = 0
    learning_rate: float = 3e-4
    weight_decay: float = 0.01
    warmup_fraction: float = 0.05
    num_workers: int = 4
    loss: str = "bce"
    focal_gamma: float = 2.0
    channel_weights: dict[str, float] = field(
        default_factory=lambda: {"in": 1.0, "out": 1.0, "inside": 0.5}
    )
    amp: bool = True
    seed: int = 0


@dataclass(frozen=True)
class RunSpec:
    """A full experiment: data, model and optimisation."""

    name: str
    dataset: Any = field(default_factory=DatasetSpec)
    model: Any = field(default_factory=ModelSpec)
    train: TrainSpec = field(default_factory=TrainSpec)
    encoder: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-serialisable description of the run."""
        payload: dict[str, Any] = json.loads(json.dumps(asdict(self), default=str))
        return payload


def pos_weights(rates: dict[str, float]) -> torch.Tensor:
    """Turn observed positive rates into per-channel loss weights.

    A channel positive one step in fifty gets its positives weighted by fifty,
    capped, which is what keeps the boundary heads from collapsing onto "never".
    """
    values = []
    for channel in CHANNELS:
        rate = max(rates.get(channel, 0.0), 1e-4)
        values.append(min((1.0 - rate) / rate, MAX_POS_WEIGHT))
    return torch.tensor(values, dtype=torch.float32)


class MaskedChannelLoss(nn.Module):
    """Binary cross-entropy per channel, masked and weighted.

    The mask drops the steps that fall past the end of a game, which are padded
    silence and would otherwise be learned as genuine dead time.
    """

    def __init__(self, spec: TrainSpec, rates: dict[str, float]) -> None:
        """Build the loss from the observed target rates."""
        super().__init__()
        self.spec = spec
        self.register_buffer("pos_weight", pos_weights(rates))
        self.register_buffer(
            "channel_weight",
            torch.tensor(
                [spec.channel_weights.get(name, 1.0) for name in CHANNELS],
                dtype=torch.float32,
            ),
        )

    def forward(
        self, logits: torch.Tensor, target: torch.Tensor, valid: torch.Tensor
    ) -> torch.Tensor:
        """Return the mean loss over valid steps.

        Args:
            logits: ``(batch, steps, channels)``.
            target: same shape, soft targets in [0, 1].
            valid: ``(batch, steps)``, 1 where the step is real audio.
        """
        if self.spec.loss == "focal":
            probabilities = torch.sigmoid(logits)
            focus = (target - probabilities).abs() ** self.spec.focal_gamma
            element = focus * nn.functional.binary_cross_entropy_with_logits(
                logits, target, reduction="none"
            )
        else:
            element = nn.functional.binary_cross_entropy_with_logits(
                logits, target, reduction="none", pos_weight=self.pos_weight
            )

        element = element * self.channel_weight
        mask = valid.unsqueeze(-1)
        loss: torch.Tensor = (
            (element * mask).sum() / mask.sum().clamp_min(1.0) / len(CHANNELS)
        )
        return loss


def average_precision(scores: np.ndarray, targets: np.ndarray) -> float:
    """Return the average precision of one channel over pooled steps.

    Threshold-free, so a run can be compared before the decoding thresholds are
    tuned.
    """
    positives = targets >= POSITIVE_LEVEL
    if not positives.any():
        return float("nan")

    order = np.argsort(-scores)
    hits = positives[order]
    cumulative = np.cumsum(hits)
    precision = cumulative / np.arange(1, len(hits) + 1)
    return float(precision[hits].sum() / positives.sum())


def selection_score(metrics: dict[str, Any]) -> float:
    """Return the score the best checkpoint is chosen on.

    The mean average precision of the boundary channels: what the tool is
    actually for is finding the in and out instants, and `inside` is easy
    enough that including it would drown the signal.
    """
    values = [
        metrics[f"ap_{channel}"]
        for channel in SELECTION_CHANNELS
        if not math.isnan(metrics.get(f"ap_{channel}", math.nan))
    ]
    return sum(values) / len(values) if values else -math.inf


def _learning_rate(step: int, *, total_steps: int, spec: TrainSpec) -> float:
    """Return the learning rate of one step: linear warmup, cosine decay."""
    warmup = max(int(total_steps * spec.warmup_fraction), 1)
    if step < warmup:
        return spec.learning_rate * step / warmup
    progress = (step - warmup) / max(total_steps - warmup, 1)
    return spec.learning_rate * 0.5 * (1.0 + math.cos(math.pi * progress))


def _forward(model: nn.Module, inputs: torch.Tensor, steps: int | None) -> torch.Tensor:
    """Call a model that may or may not take an explicit output length.

    The waveform model needs to be told how many steps to produce, because the
    frontend's frame count depends on rounding. The embedding head predicts one
    step per input step and needs nothing.
    """
    if steps is None:
        output: torch.Tensor = model(inputs)
        return output
    return model(inputs, steps=steps)  # type: ignore[no-any-return]


@torch.no_grad()
def evaluate_windows(
    model: nn.Module,
    loader: DataLoader[dict[str, Any]],
    loss_fn: nn.Module,
    device: torch.device,
    steps: int | None,
    input_key: str = "waveform",
) -> dict[str, float]:
    """Score the model on validation windows, without decoding.

    Cheap enough to run every epoch; full-game decoding is the job of the
    ``evaluate`` command.
    """
    model.eval()
    total_loss, batches = 0.0, 0
    collected: list[tuple[np.ndarray, np.ndarray]] = []

    for batch in loader:
        inputs = batch[input_key].to(device, non_blocking=True)
        target = batch["target"].to(device, non_blocking=True)
        valid = batch["valid"].to(device, non_blocking=True)

        with torch.autocast(device.type, enabled=device.type == "cuda"):
            logits = _forward(model, inputs, steps)
        total_loss += float(loss_fn(logits.float(), target, valid))
        batches += 1

        mask = valid.bool().cpu().numpy().reshape(-1)
        collected.append(
            (
                torch.sigmoid(logits.float())
                .cpu()
                .numpy()
                .reshape(-1, len(CHANNELS))[mask],
                target.cpu().numpy().reshape(-1, len(CHANNELS))[mask],
            )
        )

    scores = np.concatenate([item[0] for item in collected])
    targets = np.concatenate([item[1] for item in collected])
    metrics = {"val_loss": total_loss / max(batches, 1)}
    for channel in CHANNELS:
        index = CHANNEL_INDEX[channel]
        metrics[f"ap_{channel}"] = average_precision(
            scores[:, index], targets[:, index]
        )
    return metrics


@dataclass
class _EpochContext:
    """Everything an epoch needs beyond the model and its data."""

    loss_fn: nn.Module
    optimizer: torch.optim.Optimizer
    scaler: GradScaler
    device: torch.device
    spec: TrainSpec
    steps: int | None
    total_steps: int
    input_key: str = "waveform"


def _run_epoch(
    model: nn.Module,
    loader: DataLoader[dict[str, Any]],
    context: _EpochContext,
    global_step: int,
) -> tuple[float, int]:
    """Run one training epoch.

    Returns:
        The mean loss over the epoch, and the updated global step counter.
    """
    loss_fn, optimizer, scaler = context.loss_fn, context.optimizer, context.scaler
    device, spec, steps = context.device, context.spec, context.steps
    model.train()
    running, batches = 0.0, 0

    for batch in loader:
        learning_rate = _learning_rate(
            global_step, total_steps=context.total_steps, spec=spec
        )
        for group in optimizer.param_groups:
            group["lr"] = learning_rate

        inputs = batch[context.input_key].to(device, non_blocking=True)
        target = batch["target"].to(device, non_blocking=True)
        valid = batch["valid"].to(device, non_blocking=True)

        with torch.autocast(device.type, enabled=spec.amp):
            logits = _forward(model, inputs, steps)
            loss = loss_fn(logits.float(), target, valid)

        optimizer.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        scaler.step(optimizer)
        scaler.update()

        running += float(loss)
        batches += 1
        global_step += 1

    return running / max(batches, 1), global_step


@dataclass(frozen=True)
class TrainingInputs:
    """The concrete pieces a run needs beyond its specification."""

    train_set: TargetRatesDataset
    val_set: TargetRatesDataset
    model: nn.Module
    input_key: str = "waveform"
    steps: int | None = None


def train(
    run: RunSpec,
    inputs: TrainingInputs,
    *,
    output_dir: Path,
    device: torch.device,
) -> dict[str, Any]:
    """Train a model and write everything needed to reuse it.

    Args:
        run: the full experiment description.
        inputs: the datasets and the model to train.
        output_dir: where the checkpoint, config and history land.
        device: where to run.

    Returns:
        The training history, one entry per epoch.
    """
    torch.manual_seed(run.train.seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_set, val_set = inputs.train_set, inputs.val_set
    model = inputs.model.to(device)
    steps, input_key = inputs.steps, inputs.input_key
    rates = train_set.target_rates()

    print(f"Fenêtres par epoch : {len(train_set)} (val {len(val_set)})")
    print(
        "Taux de positifs   : "
        + "  ".join(f"{name} {rates[name]:.4f}" for name in CHANNELS)
    )
    weights = pos_weights(rates)
    print(
        "Poids de la loss   : "
        + "  ".join(f"{name} x{weights[i]:.1f}" for i, name in enumerate(CHANNELS))
    )

    print(
        f"Paramètres         : {sum(p.numel() for p in model.parameters()) / 1e6:.2f} M"
    )
    loss_fn = MaskedChannelLoss(run.train, rates).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=run.train.learning_rate,
        weight_decay=run.train.weight_decay,
    )
    scaler = GradScaler(device.type, enabled=run.train.amp)

    loader_args: dict[str, Any] = {
        "batch_size": run.train.batch_size,
        "num_workers": run.train.num_workers,
        "pin_memory": device.type == "cuda",
        "persistent_workers": run.train.num_workers > 0,
    }
    val_loader: DataLoader[dict[str, Any]] = DataLoader(
        cast("Dataset[dict[str, Any]]", val_set), shuffle=False, **loader_args
    )

    total_steps = max(run.train.epochs * (len(train_set) // run.train.batch_size), 1)
    context = _EpochContext(
        loss_fn=loss_fn,
        optimizer=optimizer,
        scaler=scaler,
        device=device,
        spec=run.train,
        steps=steps,
        total_steps=total_steps,
        input_key=input_key,
    )
    history: list[dict[str, Any]] = []
    best = -math.inf
    since_best = 0
    global_step = 0

    for epoch in range(run.train.epochs):
        train_set.resample(epoch)
        train_loader: DataLoader[dict[str, Any]] = DataLoader(
            cast("Dataset[dict[str, Any]]", train_set),
            shuffle=True,
            drop_last=True,
            **loader_args,
        )
        started = time.monotonic()
        running, global_step = _run_epoch(model, train_loader, context, global_step)

        metrics = evaluate_windows(model, val_loader, loss_fn, device, steps, input_key)
        entry = {
            "epoch": epoch,
            "train_loss": running,
            "seconds": round(time.monotonic() - started, 1),
            **metrics,
        }
        history.append(entry)
        print(
            f"epoch {epoch:3d}  train {entry['train_loss']:.4f}  "
            f"val {entry['val_loss']:.4f}  "
            + "  ".join(f"AP-{name} {entry[f'ap_{name}']:.3f}" for name in CHANNELS)
            + f"  {entry['seconds']:.0f}s"
            + ("  *" if selection_score(entry) > best else "")
        )

        score = selection_score(entry)
        entry["selection_score"] = score
        if score > best:
            best = score
            since_best = 0
            torch.save(
                {
                    "model": model.state_dict(),
                    "run": run.to_json(),
                    "epoch": epoch,
                    "rates": rates,
                },
                output_dir / "best.pt",
            )

        (output_dir / "history.json").write_text(json.dumps(history, indent=2))
        (output_dir / "run.json").write_text(json.dumps(run.to_json(), indent=2))

        since_best += 1
        if run.train.patience and since_best > run.train.patience:
            print(
                f"Arrêt anticipé : {run.train.patience} epochs sans progrès "
                f"sur le score de sélection."
            )
            break

    return {"history": history, "best_score": best}
