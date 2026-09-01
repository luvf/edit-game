"""What the database offers as training material.

A game is usable when it carries a cut file *and* an audio source that is
actually on disk. Everything else is reported as a rejection rather than
silently dropped, because the missing archives are being rendered over time and
the coverage is worth watching between runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from game_autoedit.config import (
    ARCHIVE_QUALITIES,
    AUDIO_QUALITY,
    CUT_TYPE_PRIORITY,
    DEFAULT_FPS,
)
from game_autoedit.data.labels import has_points

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from core.models.cut import Cut
    from core.models.game import Game


@dataclass(frozen=True)
class LabeledGame:
    """One game with both a cut file and an audio source on disk."""

    game_id: int
    name: str
    slug: str
    tournament: str
    cut_id: int
    cut_type: str
    cut_json_path: Path
    audio_source: Path
    fps: float
    quality: str = AUDIO_QUALITY

    @property
    def key(self) -> str:
        """Return a stable, human-readable identifier for logs and filenames."""
        return f"{self.game_id}:{self.slug or self.name}"


@dataclass(frozen=True)
class Rejection:
    """A game that carries a cut but cannot be used, and why."""

    game_id: int
    name: str
    tournament: str
    reason: str


@dataclass(frozen=True)
class Catalog:
    """The usable games and the ones held back."""

    games: list[LabeledGame]
    rejected: list[Rejection]

    def tournaments(self) -> list[str]:
        """Return the sorted tournament names covered by the usable games."""
        return sorted({game.tournament for game in self.games})

    def by_tournament(self) -> dict[str, list[LabeledGame]]:
        """Group the usable games by tournament name."""
        grouped: dict[str, list[LabeledGame]] = {}
        for game in self.games:
            grouped.setdefault(game.tournament, []).append(game)
        return grouped

    def rejection_counts(self) -> dict[str, int]:
        """Count rejections per reason."""
        counts: dict[str, int] = {}
        for rejection in self.rejected:
            counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
        return counts


def pick_cut(cuts: Sequence[Cut]) -> Cut:
    """Return the most trustworthy cut of a game.

    Games occasionally carry several cuts, mixing a reconstructed one with the
    one that came from the actual edit. `CUT_TYPE_PRIORITY` decides; ties go to
    the most recent row.
    """
    order = {type_cut: rank for rank, type_cut in enumerate(CUT_TYPE_PRIORITY)}
    return min(
        cuts,
        key=lambda cut: (order.get(cut.type_cut, len(order)), -(cut.pk or 0)),
    )


@dataclass(frozen=True)
class AudioSource:
    """Where a game's audio comes from, or why it cannot be read."""

    path: Path | None
    fps: float = DEFAULT_FPS
    quality: str = AUDIO_QUALITY
    reason: str | None = None


def _qualities_for(quality: str) -> tuple[str, ...]:
    """Return the quality names to try, in order of preference."""
    return ARCHIVE_QUALITIES if quality == AUDIO_QUALITY else (quality,)


def _audio_source(game: Game, quality: str) -> AudioSource:
    """Return the on-disk audio source of a game.

    The archive slot is tried under every name it has historically been filed
    under, so a master rendered before the "archive" quality existed is still
    found.
    """
    video = game.archive_video if quality == AUDIO_QUALITY else game.video_proxy
    if video is None:
        return AudioSource(None, reason=f"pas de vidéo {quality} rattachée")

    known: list[str] = []
    for candidate in _qualities_for(quality):
        try:
            video_file = video.get_file(candidate)
        except FileNotFoundError:
            continue
        known.append(candidate)
        if video_file.exists_on_disk:
            return AudioSource(
                Path(video_file.path),
                fps=video_file.fps or DEFAULT_FPS,
                quality=candidate,
            )

    if known:
        return AudioSource(None, reason=f"fichier {'/'.join(known)} absent du disque")
    return AudioSource(None, reason=f"pas de fichier {quality} en base")


def build_catalog(
    *,
    quality: str = AUDIO_QUALITY,
    tournaments: Iterable[str] | None = None,
    game_ids: Iterable[int] | None = None,
) -> Catalog:
    """Scan the database for usable games.

    Args:
        quality: which VideoFile quality to read audio from.
        tournaments: restrict to these tournament names, if given.
        game_ids: restrict to these game ids, if given.

    Returns:
        The usable games and the rejected ones.
    """
    from core.models.game import Game

    queryset = (
        Game.objects.filter(cuts__isnull=False)
        .select_related("tournament", "archive_video", "video_proxy")
        .prefetch_related("cuts", "archive_video__files", "video_proxy__files")
        .distinct()
        .order_by("id")
    )
    if tournaments is not None:
        queryset = queryset.filter(tournament__name__in=list(tournaments))
    if game_ids is not None:
        queryset = queryset.filter(pk__in=list(game_ids))

    games: list[LabeledGame] = []
    rejected: list[Rejection] = []

    for game in queryset:
        tournament = game.tournament.name
        cuts = list(game.cuts.all())
        if not cuts:
            rejected.append(Rejection(game.pk, game.name, tournament, "aucun cut"))
            continue

        cut = pick_cut(cuts)
        cut_path = Path(cut.json_file.path)
        if not cut_path.exists():
            rejected.append(
                Rejection(game.pk, game.name, tournament, "fichier de cut absent")
            )
            continue

        if not has_points(cut_path):
            rejected.append(
                Rejection(game.pk, game.name, tournament, "fichier de cut vide")
            )
            continue

        source = _audio_source(game, quality)
        if source.path is None:
            rejected.append(
                Rejection(game.pk, game.name, tournament, source.reason or "?")
            )
            continue

        games.append(
            LabeledGame(
                game_id=game.pk,
                name=game.name,
                slug=game.slug,
                tournament=tournament,
                cut_id=cut.pk,
                cut_type=cut.type_cut,
                cut_json_path=cut_path,
                audio_source=source.path,
                fps=source.fps,
                quality=source.quality,
            )
        )

    return Catalog(games=games, rejected=rejected)
