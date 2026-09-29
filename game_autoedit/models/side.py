"""Who won a point, read from the pictures around its end.

This is deliberately *not* a channel of the tagger. The tagger's trunk is
trained almost entirely by the boundary channels, which have no use for left
and right, and only fifteen games of two hundred say who scored: a batch of
windows almost never holds two labelled points, so the side output learned one
example at a time and collapsed onto a constant that flipped every epoch.

So the side is a small classifier of its own, over one vector per point. It
trains in seconds on a few hundred points, it cannot disturb the boundaries,
and it can be fitted again — or dropped — without retraining anything else.

What it reads matters more than how it learns. On the raw embeddings it scored
0.74 by game-held-out cross-validation, and answered a game it had never seen
with the same side eighteen times in a row at a confidence of 1.00: with 4608
dimensions for 200 points, it was recognising the match. Two changes fixed
that, and both say the same thing — describe the *asymmetry of the moment*,
not the look of the game:

- the left band minus the right band, so a venue, a camera and a pair of team
  colours cancel out, and mirroring becomes an exact change of sign;
- minus the game's own average, so what is left is what this instant has that
  the rest of the match does not.

Together, with each point also shown mirrored, that reads 0.84 — and 0.85 on
the points that go against their own game's dominant side, which is where a
model that merely recognised the game would fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from scipy.special import gammaln
from torch import nn

from game_autoedit.data.labels import SIDES
from game_autoedit.datasets.targets import SIDE_CHANNEL

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from game_autoedit.data.embeddings import EmbeddingStore, FusedStore
    from game_autoedit.data.labels import Segment

# Steps whose value strays this far from the mean, in standard deviations, are
# clipped: a handful of dimensions of a frozen encoder have long tails, and a
# linear model fitted on a few hundred points follows them straight into
# overfitting.
CLIP = 4.0

# A probability at which neither side is favoured.
UNDECIDED = 0.5


@dataclass(frozen=True)
class WeightProfile:
    """When to look, and how much each instant counts.

    Measured by learning the profile jointly with the classifier, on several
    classic families — Poisson, gamma, chi-2, log-normal, Gaussian, and a free
    profile of one weight per step. They all converge on the same place, 2.5
    to 3 seconds before the cut, and none beats the others by more than the
    spread between fold draws. A gamma turned the other way round, looking
    *after* the cut, collapses from 0.90 to 0.80: there is nothing to read
    once the point is over.

    Poisson with ``rate`` 2.3 is what the learning settled on, and what the
    default is. The family stays a parameter because the right answer here is
    to learn it again on more labelled games, not to trust 303 points.

    Attributes:
        kind: ``poisson`` weights by the seconds before the end; ``gaussian``
            centres a bell on `rate` seconds before it; ``flat`` counts every
            instant of ``[end - rate - spread, end - rate]`` alike.
        rate: where the profile sits, in seconds before the point's end: the
            Poisson's mean (its peak sits half a second earlier), the
            Gaussian's centre, or the near edge of the flat window.
        spread: the Gaussian's sigma, or the flat window's length. Unused by
            Poisson, whose spread is its rate.
        before: how far before the end the window opens.
        after: where it closes, counted from the end; negative stops before it.
    """

    kind: str = "poisson"
    rate: float = 2.3
    spread: float = 1.0
    before: float = 10.0
    after: float = 0.0

    def weights(self, offsets: np.ndarray) -> np.ndarray:
        """Return the weight of each instant, from its offset to the end.

        Args:
            offsets: seconds from the point's end, negative before it.
        """
        ahead = -offsets  # seconds before the end
        if self.kind == "flat":
            return ((ahead >= self.rate) & (ahead <= self.rate + self.spread)).astype(
                np.float32
            )
        if self.kind == "gaussian":
            return np.exp(-0.5 * ((ahead - self.rate) / self.spread) ** 2).astype(
                np.float32
            )
        if self.kind != "poisson":
            raise ValueError(f"profil de pondération inconnu : {self.kind}")
        # The Poisson mass as a continuous profile, zero at the cut itself.
        safe = np.clip(ahead, 1e-3, None)
        weights = np.exp(
            safe * np.log(self.rate) - self.rate - gammaln(safe + 1.0)
        ).astype(np.float32)
        return np.where(ahead > 0, weights, 0.0).astype(np.float32)

    def window(self, segments: Sequence[Segment], index: int) -> tuple[float, float]:
        """Return the stretch of a point this profile may read.

        Held off the neighbouring points, so a window never reads the moment
        that decided another one. The point's own start is not a bound:
        measured, it changes nothing, since only 2 labelled points of 303 are
        shorter than the window.
        """
        segment = segments[index]
        first = segment.end - self.before
        last = segment.end + self.after
        if index > 0:
            first = max(first, segments[index - 1].end + max(self.after, 0.0))
        if index + 1 < len(segments):
            last = min(last, segments[index + 1].start)
        return first, max(last, first)

    def to_json(self) -> dict[str, Any]:
        """Return the profile as it travels in a cut's comment."""
        return {
            "kind": self.kind,
            "rate": self.rate,
            "spread": self.spread,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_json(cls, payload: Any) -> WeightProfile:
        """Return the profile a cut's comment describes, or the default."""
        if not isinstance(payload, dict):
            return cls()
        fields = {"kind", "rate", "spread", "before", "after"}
        return cls(**{k: v for k, v in payload.items() if k in fields})


@dataclass(frozen=True)
class Bands:
    """Where an image encoder's vertical bands sit in an embedding."""

    start: int
    width: int

    @property
    def left(self) -> slice:
        """Return the columns of the left band."""
        return slice(self.start + self.width, self.start + 2 * self.width)

    @property
    def right(self) -> slice:
        """Return the columns of the right band."""
        return slice(self.start + 3 * self.width, self.start + 4 * self.width)


def band_layout(store: EmbeddingStore | FusedStore) -> Bands | None:
    """Return where the picture bands live in `store`, or None without any.

    The side needs pictures: the sound cannot carry it. A mid/side recording
    encodes its spatial channel as ``L - R``, whose sign a spectrogram throws
    away, so the two sides come out identical.
    """
    from game_autoedit.encoders.base import VIDEO_ENCODERS
    from game_autoedit.encoders.dinov2 import BANDS

    # A fused store says where each cache sits; a single one is all there is.
    fused = getattr(store, "spans", None)
    spans = (
        [(span.encoder, span.start, span.end) for span in fused]
        if fused
        else [(store.encoder, 0, store.dim)]
    )
    for encoder, start, end in spans:
        if encoder in VIDEO_ENCODERS:
            return Bands(start=start, width=(end - start) // (1 + BANDS))
    return None


def step_features(
    store: EmbeddingStore | FusedStore, game_id: int
) -> np.ndarray | None:
    """Return the side features of a whole game, one vector per step.

    The left band minus the right band, minus that difference's average over
    the game. See this module's docstring for why those two subtractions are
    the whole difference between reading the action and recognising the match.

    Returns:
        ``(steps, width)`` float32, or None when the store holds no picture.
    """
    bands = band_layout(store)
    if bands is None:
        return None
    embeddings = np.asarray(store.load(game_id), dtype=np.float32)
    asymmetry = embeddings[:, bands.left] - embeddings[:, bands.right]
    centred: np.ndarray = asymmetry - asymmetry.mean(axis=0, keepdims=True)
    return centred


def pooled_features(
    features: np.ndarray,
    rate: float,
    segments: Sequence[Segment],
    profile: WeightProfile | None = None,
) -> np.ndarray:
    """Return one vector per segment: its end window, averaged.

    Args:
        features: ``(steps, dim)`` for the whole game, as `step_features`
            built them.
        rate: embedding steps per second.
        segments: the points to describe, in timeline order.
        profile: when to look, and how much each instant counts.

    Returns:
        ``(len(segments), dim)`` float32; a segment whose window falls outside
        the embeddings comes back as zeros.
    """
    profile = profile or WeightProfile()
    pooled = np.zeros((len(segments), features.shape[1]), dtype=np.float32)
    for index in range(len(segments)):
        low, high, weights = _window_weights(profile, segments, index, rate)
        if high > low and weights.sum() > 0:
            block = np.asarray(features[low:high], dtype=np.float32)
            pooled[index] = (block * weights[:, None]).sum(0) / weights.sum()
    return pooled


def _window_weights(
    profile: WeightProfile, segments: Sequence[Segment], index: int, rate: float
) -> tuple[int, int, np.ndarray]:
    """Return a point's window in steps, and the weight of each of them."""
    first, last = profile.window(segments, index)
    low, high = max(int(first * rate), 0), max(int(last * rate), 0)
    if high <= low:
        return low, high, np.zeros(0, dtype=np.float32)
    offsets = np.arange(low, high) / rate - segments[index].end
    return low, high, profile.weights(offsets)


@dataclass(frozen=True)
class SideFit:
    """How the classifier was fitted, kept so a run can be reproduced."""

    epochs: int = 400
    learning_rate: float = 0.05
    weight_decay: float = 0.1
    hidden: int = 0


class SideClassifier(nn.Module):
    """Tells which side of the picture won a point, from its end window.

    Standardising the features is part of the model, not of the data
    preparation: the statistics are fitted on the training points and travel
    with the weights, so a game scored later is described exactly as the
    training ones were.
    """

    def __init__(
        self,
        dim: int,
        spec: SideFit | None = None,
        profile: WeightProfile | None = None,
    ) -> None:
        """Build the classifier for `dim`-wide pooled embeddings."""
        super().__init__()
        self.spec = spec or SideFit()
        self.profile = profile or WeightProfile()
        self.register_buffer("mean", torch.zeros(dim))
        self.register_buffer("scale", torch.ones(dim))
        self.net = (
            nn.Linear(dim, 1)
            if self.spec.hidden <= 0
            else nn.Sequential(
                nn.Linear(dim, self.spec.hidden),
                nn.GELU(),
                nn.Linear(self.spec.hidden, 1),
            )
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Return the logit that each point was won on the left."""
        standard = ((features - self.mean) / self.scale).clamp(-CLIP, CLIP)
        logits: torch.Tensor = self.net(standard).squeeze(-1)
        return logits

    @torch.no_grad()
    def probabilities(self, features: np.ndarray) -> np.ndarray:
        """Return, for each pooled point, the probability of a left win."""
        self.eval()
        tensor = torch.from_numpy(np.asarray(features, dtype=np.float32))
        tensor = tensor.to(next(self.parameters()).device)
        left: np.ndarray = torch.sigmoid(self(tensor)).cpu().numpy()
        return left

    def fit(self, features: np.ndarray, targets: np.ndarray) -> float:
        """Fit on pooled points and return the final training loss.

        Args:
            features: ``(points, dim)`` pooled embeddings.
            targets: ``(points,)``, 1 for a point won on the left.
        """
        device = next(self.parameters()).device
        tensor = torch.from_numpy(np.asarray(features, dtype=np.float32)).to(device)
        labels = torch.from_numpy(np.asarray(targets, dtype=np.float32)).to(device)
        self.mean.copy_(tensor.mean(0))
        self.scale.copy_(tensor.std(0).clamp_min(1e-6))

        self.train()
        optimiser = torch.optim.Adam(
            self.net.parameters(),
            lr=self.spec.learning_rate,
            weight_decay=self.spec.weight_decay,
        )
        loss = torch.zeros(())
        for _ in range(self.spec.epochs):
            optimiser.zero_grad()
            loss = nn.functional.binary_cross_entropy_with_logits(self(tensor), labels)
            loss.backward()  # type: ignore[no-untyped-call]
            optimiser.step()
        return float(loss)

    def save(self, path: Path) -> None:
        """Write the weights and how they were fitted."""
        torch.save(
            {
                "state": self.state_dict(),
                "dim": int(self.mean.shape[0]),
                "fit": vars(self.spec),
                "profile": self.profile.to_json(),
            },
            path,
        )

    @classmethod
    def load(cls, path: Path, device: torch.device | None = None) -> SideClassifier:
        """Return the classifier stored at `path`, ready to score."""
        payload: dict[str, Any] = torch.load(
            path, map_location=device or "cpu", weights_only=False
        )
        model = cls(
            int(payload["dim"]),
            SideFit(**payload["fit"]),
            WeightProfile.from_json(payload.get("profile")),
        )
        model.load_state_dict(payload["state"])
        model.eval()
        return model.to(device or "cpu")


def training_points(
    store: EmbeddingStore | FusedStore,
    games: Sequence[Any],
    profile: WeightProfile | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Collect every labelled point of `games` as one pooled example each.

    Args:
        store: the embedding cache to read.
        games: prepared games, carrying their labels.
        profile: when to look around each point's end.

    Returns:
        The pooled features, the targets (1 for left), and the game id of each
        point, for scoring by game.
    """
    collected: list[np.ndarray] = []
    targets: list[float] = []
    owners: list[int] = []

    for prepared in games:
        labels = prepared.labels
        if not labels.has_sides:
            continue
        features = step_features(store, prepared.game.game_id)
        if features is None:
            continue
        pooled = pooled_features(features, store.rate, labels.segments, profile)
        for index, segment in enumerate(labels.segments):
            if segment.point not in SIDES:
                continue
            collected.append(pooled[index])
            targets.append(1.0 if segment.point == SIDE_CHANNEL else 0.0)
            owners.append(prepared.game.game_id)

    if not collected:
        dim = width_of(store)
        return (
            np.zeros((0, dim), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            np.zeros(0, dtype=np.int64),
        )
    return (
        np.stack(collected),
        np.array(targets, dtype=np.float32),
        np.array(owners, dtype=np.int64),
    )


def mirrored(
    features: np.ndarray, targets: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return the points plus the same points seen in a mirror.

    The features are the left band minus the right one, so a mirror is exactly
    a change of sign — no approximation, unlike flipping whole embeddings.
    Every labelled point then counts twice, and the classifier cannot learn
    that a given camera tends to film the winners on one side.
    """
    return (
        np.concatenate([features, -features]),
        np.concatenate([targets, 1.0 - targets]),
    )


def step_logits(classifier: SideClassifier, features: np.ndarray) -> np.ndarray | None:
    """Return the classifier's logit at every step, or None if it cannot be.

    A linear classifier is affine, so averaging its logit over a window gives
    exactly the logit of the averaged window: one curve along the game answers
    for *any* cutting of it, which is what lets a re-decode with other
    thresholds keep its sides without the model or the embeddings. A hidden
    layer breaks that equality, and there this returns None.
    """
    if classifier.spec.hidden > 0:
        return None
    with torch.no_grad():
        device = next(classifier.parameters()).device
        tensor = torch.from_numpy(np.asarray(features, dtype=np.float32)).to(device)
        logits: np.ndarray = classifier(tensor).cpu().numpy().astype(np.float32)
    return logits


def sides_from_logits(
    logits: np.ndarray,
    times: np.ndarray,
    segments: Sequence[Segment],
    profile: WeightProfile | None = None,
) -> list[tuple[str, float]] | None:
    """Return who won each segment, from the stored per-step side curve.

    Args:
        logits: the side logit at every step, as `step_logits` produced it.
        times: the centre time of every step.
        segments: the points to answer for, in timeline order.
        profile: the weighting the classifier was fitted with. It has to be
            the same one, or the curve answers a question nobody asked.

    Returns:
        One ``(side, confidence)`` per segment, or None without a curve.
    """
    if logits is None or not len(logits):
        return None
    profile = profile or WeightProfile()
    rate = 1.0 / float(times[1] - times[0]) if len(times) > 1 else 1.0
    answers: list[tuple[str, float]] = []
    for index in range(len(segments)):
        low, high, weights = _window_weights(profile, segments, index, rate)
        high = min(high, len(logits))
        weights = weights[: max(high - low, 0)]
        total = float(weights.sum()) if len(weights) else 0.0
        mean = float((logits[low:high] * weights).sum() / total) if total > 0 else 0.0
        left = float(1.0 / (1.0 + np.exp(-mean)))
        answers.append(("left", left) if left >= UNDECIDED else ("right", 1.0 - left))
    return answers


def sides_for(
    classifier: SideClassifier | None,
    store: EmbeddingStore | FusedStore,
    game_id: int,
    segments: Sequence[Segment],
) -> list[tuple[str, float]] | None:
    """Return who won each segment, and how sure the classifier is.

    Returns:
        One ``(side, confidence)`` per segment, or None without a classifier.
    """
    if classifier is None or not segments:
        return None
    features = step_features(store, game_id)
    if features is None:
        return None
    pooled = pooled_features(features, store.rate, segments, classifier.profile)
    left = classifier.probabilities(pooled)
    return [
        ("left", float(value)) if value >= UNDECIDED else ("right", float(1.0 - value))
        for value in left
    ]


def width_of(store: EmbeddingStore | FusedStore) -> int:
    """Return how wide this store's side features are."""
    bands = band_layout(store)
    return bands.width if bands is not None else 0


def accuracy(probabilities: np.ndarray, targets: np.ndarray) -> float:
    """Return the share of points whose side is called right."""
    if not len(targets):
        return float("nan")
    return float(((probabilities >= UNDECIDED) == (targets >= UNDECIDED)).mean())
