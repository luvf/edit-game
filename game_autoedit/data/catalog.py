"""What the database offers as training material, and what it can be run on.

A game is usable when it carries a cut file *and* an audio source that is
actually on disk. Everything else is reported as a rejection rather than
silently dropped, because the missing archives are being rendered over time and
the coverage is worth watching between runs.

Training reads archives only -- one audio profile, the one the measurements
were made on. Proposing is allowed to fall back to a game's rushes, because a
game filmed yesterday has no archive yet and waiting for one is hours.
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
    PREDICTED_CUT_TYPE,
    RUSH_QUALITY,
    VIDEO_QUALITIES,
)
from game_autoedit.data.labels import has_points, has_sides

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from core.models.cut import Cut
    from core.models.game import Game


@dataclass(frozen=True)
class LabeledGame:
    """One game with both a cut file and an audio source on disk.

    `audio_sources` is a list because a game without an archive is read from
    its rushes, which are several files concatenated in order -- exactly the
    order the archive would have been rendered from.
    """

    game_id: int
    name: str
    slug: str
    tournament: str
    cut_id: int
    cut_type: str
    cut_json_path: Path
    audio_sources: tuple[Path, ...]
    fps: float
    quality: str = AUDIO_QUALITY
    video_sources: tuple[Path, ...] = ()

    @property
    def key(self) -> str:
        """Return a stable, human-readable identifier for logs and filenames."""
        return f"{self.game_id}:{self.slug or self.name}"

    @property
    def audio_source(self) -> Path:
        """Return the first audio source, for probing and for logs."""
        return self.audio_sources[0]


class UnusableGameError(RuntimeError):
    """A game the model cannot be run on, with the reason a user can act on."""


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

    An annotated cut comes first, whatever its type: a point that says which
    side won it has been gone over by hand, since no model writes a side, and
    that is worth more than the type it was filed under. Without this rule,
    five games of a tournament sat in the catalog with their 66 labelled sides
    ignored, read from their reconstructed `VID` twin instead.

    Then the usual order: a real edit, then a cut rebuilt from the video.
    """
    order = {type_cut: rank for rank, type_cut in enumerate(CUT_TYPE_PRIORITY)}

    def rank(cut: Cut) -> tuple[int, int, int]:
        annotated = has_sides(Path(cut.json_file.path))
        return (
            0 if annotated else 1,
            order.get(cut.type_cut, len(order)),
            -(cut.pk or 0),
        )

    return min(cuts, key=rank)


@dataclass(frozen=True)
class AudioSource:
    """Where a game's audio comes from, or why it cannot be read."""

    paths: tuple[Path, ...]
    fps: float = DEFAULT_FPS
    quality: str = AUDIO_QUALITY
    reason: str | None = None

    @property
    def path(self) -> Path | None:
        """Return the first file, or None when there is nothing to read."""
        return self.paths[0] if self.paths else None


def is_human_cut(cut: Cut) -> bool:
    """Tell whether a cut can be trusted as training material.

    Every cut is, except a proposal nobody has gone over. A proposal that says
    who scored its points has been: the model never writes a side, so the side
    is the trace of the human pass that also corrected the boundaries.
    """
    if cut.type_cut != PREDICTED_CUT_TYPE:
        return True
    return has_sides(Path(cut.json_file.path))


def video_sources(game: Game, audio: AudioSource) -> tuple[Path, ...]:
    """Return the files a game's pictures are read from.

    A proxy first, the low one by preference: it shares the archive's
    timeline to the millisecond and decodes an order of magnitude faster than
    the AV1 archive, which the card at hand cannot decode in hardware — and
    the encoder looks at the frames at a few hundred pixels wide anyway. The audio source otherwise,
    archive or rushes, which carries the same timeline by construction.
    """
    proxy = game.video_proxy
    if proxy is None:
        return audio.paths
    for quality in VIDEO_QUALITIES:
        try:
            video_file = proxy.get_file(quality)
        except FileNotFoundError:
            continue
        if video_file.exists_on_disk:
            return (Path(video_file.path),)
    return audio.paths


# How far a proxy's length may stray from its audio source's before its
# timeline is not trusted to be the same one.
ALIGNMENT_TOLERANCE = 1.0


def aligned_video_sources(game: LabeledGame) -> tuple[Path, ...]:
    """Return the video to read pictures from, once its timeline is checked.

    A proxy is only as good as its timeline, and not every proxy was rendered
    from the rushes the archive was: one found in the catalog lasts 28 min
    against the archive's 41. A proxy whose length strays from the audio
    source is dropped for the audio source itself, slower to decode but on
    the timeline the labels refer to. Probing costs a few ffprobe calls, which
    is why this runs when a game is encoded rather than in `build_catalog`.
    """
    from game_autoedit.data.audio import probe_duration

    if not game.video_sources or game.video_sources == game.audio_sources:
        return game.audio_sources

    def total(paths: tuple[Path, ...]) -> float | None:
        durations = [probe_duration(path) for path in paths]
        if any(duration is None for duration in durations):
            return None
        return sum(duration for duration in durations if duration is not None)

    video, audio = total(game.video_sources), total(game.audio_sources)
    if video is None or audio is None or abs(video - audio) > ALIGNMENT_TOLERANCE:
        return game.audio_sources
    return game.video_sources


def _qualities_for(quality: str) -> tuple[str, ...]:
    """Return the quality names to try, in order of preference."""
    return ARCHIVE_QUALITIES if quality == AUDIO_QUALITY else (quality,)


def _rush_source(game: Game) -> AudioSource:
    """Return the game's rushes, when all of them are on disk.

    All of them: the archive concatenates the rushes in order, and so does the
    extraction. One file short and every timestamp after the hole is wrong,
    which is worse than no proposal at all -- so a partial set is refused.

    The frame rate is probed from the first rush rather than read from the
    database: a rush carries no VideoFile row.
    """
    from game_autoedit.data.audio import probe_fps

    paths = [Path(path) for path in game.get_source_files(force_rush=True)]
    if not paths:
        return AudioSource((), reason="aucun rush déclaré")

    missing = [path.name for path in paths if not path.exists()]
    if missing:
        return AudioSource((), reason=f"rush absent du disque : {', '.join(missing)}")

    return AudioSource(
        tuple(paths),
        fps=probe_fps(paths[0]) or DEFAULT_FPS,
        quality=RUSH_QUALITY,
    )


def _audio_source(game: Game, quality: str) -> AudioSource:
    """Return the on-disk audio source of a game.

    The archive slot is tried under every name it has historically been filed
    under, so a master rendered before the "archive" quality existed is still
    found.
    """
    if quality == RUSH_QUALITY:
        return _rush_source(game)

    video = game.archive_video if quality == AUDIO_QUALITY else game.video_proxy
    if video is None:
        return AudioSource((), reason=f"pas de vidéo {quality} rattachée")

    known: list[str] = []
    for candidate in _qualities_for(quality):
        try:
            video_file = video.get_file(candidate)
        except FileNotFoundError:
            continue
        known.append(candidate)
        if video_file.exists_on_disk:
            return AudioSource(
                (Path(video_file.path),),
                fps=video_file.fps or DEFAULT_FPS,
                quality=candidate,
            )

    if known:
        return AudioSource((), reason=f"fichier {'/'.join(known)} absent du disque")
    return AudioSource((), reason=f"pas de fichier {quality} en base")


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
    # `core/models/__init__.py` is empty, so nothing registers the models at
    # app-loading time: they arrive as a side effect of `core/admin.py` being
    # imported by the admin's autodiscovery. Import Cut explicitly rather than
    # trust that chain — without it the `cuts` reverse accessor may not exist
    # yet and prefetch_related fails with "Cannot find 'cuts' on Game object".
    from core.models.cut import Cut  # noqa: F401
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
        cuts = [cut for cut in game.cuts.all() if is_human_cut(cut)]
        if not cuts:
            rejected.append(
                Rejection(game.pk, game.name, tournament, "aucun cut humain")
            )
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
                audio_sources=source.paths,
                fps=source.fps,
                quality=source.quality,
                video_sources=video_sources(game, source),
            )
        )

    return Catalog(games=games, rejected=rejected)


def predictable_game(
    game_id: int,
    *,
    cut_id: int | None = None,
    quality: str = AUDIO_QUALITY,
) -> LabeledGame:
    """Return a game the model can be run on, whether or not it is labelled.

    `build_catalog` answers "what can I train on" and needs a cut with points
    in it. Proposing a cut is the other direction: the only requirement is an
    audio source on disk, and the cut file the result will be written to is
    empty by definition.

    When no archive is there to read, the rushes it would be rendered from are
    read instead. That is the common case of the feature -- a tournament comes
    back from the field and its archives are a night of encoding away -- and it
    costs nothing in alignment: the archive is a plain concatenation of those
    same rushes, in the same order.

    Args:
        game_id: the game to run on.
        cut_id: the cut the proposal belongs to. Only its path is recorded;
            its content is never read. Defaults to the game's best cut.
        quality: which VideoFile quality to read audio from. The rush fallback
            only applies to the archive, which is the only quality that has
            one; pass `RUSH_QUALITY` to go straight to the rushes.

    Returns:
        The game, with its audio source resolved.

    Raises:
        UnusableGameError: the game does not exist, or carries no readable
            audio source.
    """
    from core.models.cut import Cut  # noqa: F401
    from core.models.game import Game

    try:
        game = Game.objects.select_related(
            "tournament", "archive_video", "video_proxy"
        ).get(pk=game_id)
    except Game.DoesNotExist as error:
        raise UnusableGameError(f"game {game_id} introuvable") from error

    source = _audio_source(game, quality)
    if source.path is None and quality == AUDIO_QUALITY:
        rushes = _rush_source(game)
        source = (
            rushes
            if rushes.path is not None
            else AudioSource((), reason=f"{source.reason} ; {rushes.reason}")
        )
    if source.path is None:
        raise UnusableGameError(
            f"game {game_id} : {source.reason}. Le modèle lit l'audio de "
            f"l'archive, ou à défaut celui des rushs : générer l'archive de "
            f"cette game, ou remettre ses rushs en place."
        )

    cuts = list(game.cuts.all())
    cut = next((c for c in cuts if c.pk == cut_id), None) if cut_id else None
    if cut is None and cuts:
        cut = pick_cut(cuts)

    return LabeledGame(
        game_id=game.pk,
        name=game.name,
        slug=game.slug,
        tournament=game.tournament.name,
        cut_id=cut.pk if cut else 0,
        cut_type=cut.type_cut if cut else PREDICTED_CUT_TYPE,
        cut_json_path=Path(cut.json_file.path) if cut else Path(),
        audio_sources=source.paths,
        fps=source.fps,
        quality=source.quality,
        video_sources=video_sources(game, source),
    )
