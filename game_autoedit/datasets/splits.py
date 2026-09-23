"""Train / validation / test partitions.

Two regimes, because they answer different questions. Splitting by game asks
"does the model work on the games I have"; holding out whole tournaments asks
"does it survive a venue, a crowd and a camera position it has never heard",
which is the one that decides whether this is usable in production.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from game_autoedit.data.catalog import LabeledGame

GroupBy = Literal["game", "tournament"]


@dataclass(frozen=True)
class SplitSpec:
    """How the usable games are partitioned.

    Attributes:
        val_fraction: share of the non-held-out games kept for validation.
        test_fraction: share kept for test; ignored when `holdout_tournaments`
            is set, since the held-out tournaments then *are* the test set.
        seed: makes the partition reproducible across runs.
        group_by: draw at the game level, or keep whole tournaments together.
        holdout_tournaments: tournaments removed from training entirely and
            used as the test set.
    """

    val_fraction: float = 0.15
    test_fraction: float = 0.15
    seed: int = 0
    group_by: GroupBy = "game"
    holdout_tournaments: tuple[str, ...] = ()


@dataclass(frozen=True)
class Split:
    """The three partitions, plus how they were obtained."""

    train: list[LabeledGame] = field(default_factory=list)
    val: list[LabeledGame] = field(default_factory=list)
    test: list[LabeledGame] = field(default_factory=list)
    spec: SplitSpec = field(default_factory=SplitSpec)

    def summary(self) -> str:
        """Return a one-line description of the partition sizes."""
        return (
            f"train {len(self.train)} / val {len(self.val)} / test {len(self.test)} "
            f"games"
        )

    def tournaments(self, part: str) -> list[str]:
        """Return the tournaments covered by one partition."""
        games: list[LabeledGame] = getattr(self, part)
        return sorted({game.tournament for game in games})


def _draw(key: str, seed: int) -> float:
    """Return a unit's fixed draw in [0, 1), from its key and the seed alone."""
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _split_units(
    units: list[tuple[str, list[LabeledGame]]],
    *,
    val_fraction: float,
    test_fraction: float,
    seed: int,
) -> tuple[list[LabeledGame], list[LabeledGame], list[LabeledGame]]:
    """Send each group of games to a part according to its own draw.

    A unit's part depends on its key and the seed, never on what else is in
    the catalog. The catalog grows — archives are rendered, corrected
    proposals come in — and a shuffle over the whole list reshuffled every
    game each time one was added: runs trained a day apart no longer shared a
    validation set, and a run evaluated after the change was partly scored on
    its own training games. The price is that the fractions hold on average
    rather than exactly, and that a catalog of a handful of games can draw no
    training game at all — which `train` reports rather than quietly moving a
    game, since moving one would make its part depend on the catalog again.
    """
    draws = sorted(((_draw(key, seed), key, games) for key, games in units))
    parts: dict[str, list[tuple[float, str, list[LabeledGame]]]] = {
        "val": [],
        "test": [],
        "train": [],
    }
    for draw in draws:
        if draw[0] < val_fraction:
            parts["val"].append(draw)
        elif draw[0] < val_fraction + test_fraction:
            parts["test"].append(draw)
        else:
            parts["train"].append(draw)

    return tuple(  # type: ignore[return-value]
        [game for _, _, games in parts[name] for game in games]
        for name in ("train", "val", "test")
    )


def make_split(games: Sequence[LabeledGame], spec: SplitSpec) -> Split:
    """Partition the catalog according to `spec`.

    Args:
        games: the usable games.
        spec: how to partition them.

    Returns:
        The three partitions. Games are never shared between them.

    Raises:
        ValueError: if a held-out tournament matches no game.
    """
    pool = list(games)
    holdout: list[LabeledGame] = []

    if spec.holdout_tournaments:
        wanted = set(spec.holdout_tournaments)
        known = {game.tournament for game in pool}
        missing = wanted - known
        if missing:
            raise ValueError(f"tournoi(s) inconnu(s) : {', '.join(sorted(missing))}")
        holdout = [game for game in pool if game.tournament in wanted]
        pool = [game for game in pool if game.tournament not in wanted]

    if spec.group_by == "tournament":
        grouped: dict[str, list[LabeledGame]] = {}
        for game in pool:
            grouped.setdefault(game.tournament, []).append(game)
        units = list(grouped.items())
    else:
        units = [(str(game.game_id), [game]) for game in pool]

    train, val, test = _split_units(
        units,
        val_fraction=spec.val_fraction,
        test_fraction=0.0 if holdout else spec.test_fraction,
        seed=spec.seed,
    )

    return Split(train=train, val=val, test=holdout or test, spec=spec)
