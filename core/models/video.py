"""Logical video asset."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.db import models
from django.utils.text import slugify

from jugger_video_manipulation.ffmpeg_utils import get_fps

if TYPE_CHECKING:
    from core.models.cut import Cut
    from core.models.game import Game
    from core.models.tournament import Tournament

# Two frame rates closer than this are the same rate read with a different
# rounding (29.97 vs 30000/1001), not a file that changed.
FPS_TOLERANCE = 1e-6


def file_exists(path: Path | str) -> bool:
    """Tell whether a path points at an existing file, whatever it holds.

    `Path.exists` only swallows the errors that mean "not there": a path too
    long for the filesystem, or one holding a null byte, raises instead. A
    row can hold such a path, and a sweep over every row must not die on it.
    """
    try:
        return Path(path).exists()
    except (OSError, ValueError):
        return False


class VideoQuerySet(models.QuerySet["Video"]):
    """Queryset helpers shared by the admin and the management commands."""

    def orphans(self) -> VideoQuerySet:
        """Return the videos nothing points at anymore.

        ``Game.video_proxy``, ``Game.archive_video`` and ``Cut.rendered_video``
        are the only relations to Video, so a row missing all three is
        unreachable: no page, no render and no API response can reach it.
        """
        return self.filter(
            game__isnull=True,
            cut__isnull=True,
            game_archive__isnull=True,
        )


class Video(models.Model):
    """Logical video asset.

    A video can be linked from a Game or a Cut.
    The physical rendered files are stored as VideoFile rows.
    """

    class Status(models.TextChoices):
        """Video generation status."""

        CREATED = "CREATED", "created"
        RENDERING = "RENDERING", "rendering"
        READY = "READY", "ready"
        FAILED = "FAILED", "failed"

    class Kind(models.TextChoices):
        """What the video is, derived from the object owning it.

        The value doubles as the media subdirectory the files are stored in.
        """

        PROXY = "proxy", "proxy"
        GENERATED_RENDERED = "generated_rendered", "generated rendered"
        ARCHIVE = "archive", "archive"
        ORPHAN = "orphan", "orpheline"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
    )
    duration = models.FloatField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VideoQuerySet.as_manager()

    class Meta:
        """Model metadata."""

        db_table = "game_edit_video"

    def __str__(self) -> str:
        """Str representation."""
        return self.name or str(self.uuid)

    @property
    def base_filename(self) -> str:
        """Build the stable base filename for this video."""
        slug = slugify(self.name) if self.name else "video"
        return f"{slug}_{self.uuid}"

    def has_quality(self, quality: str, file_format: str = "mp4") -> bool:
        """Check if a video file exists for a quality and format."""
        VideoFile.validate_quality(quality=quality, throw_exception=True)
        VideoFile.validate_format(file_format=file_format, throw_exception=True)
        return self.files.filter(quality=quality, format=file_format).exists()

    def get_file(self, quality: str, file_format: str = "mp4") -> VideoFile:
        """Return the VideoFile row for a quality and format."""
        if self.has_quality(quality, file_format=file_format):
            return self.files.get(quality=quality, format=file_format)
        raise FileNotFoundError(
            f"No video file found for quality={quality} and format={file_format}."
        )

    def path_for_quality(self, quality: str, file_format: str = "mp4") -> Path:
        """Return the existing real path for a given quality and format."""
        return self.get_file(quality, file_format=file_format).real_path

    def expected_filename(self, quality: str, file_format: str = "mp4") -> str:
        """Return the ideal filename for a future rendered file."""
        VideoFile.validate_quality(quality=quality, throw_exception=True)
        VideoFile.validate_format(file_format=file_format, throw_exception=True)

        return f"{self.base_filename}_{quality}.{file_format}"

    @property
    def owner(self) -> Game | Cut | None:
        """Return the Game or Cut this video belongs to, if any.

        An archive video is shared by every game using it as a master, so
        only the first one is returned; use ``archived_games`` for the list.
        """
        return self._resolve()[1]

    @property
    def kind(self) -> str:
        """Return the :class:`Kind` of this video."""
        return self._resolve()[0]

    @property
    def archived_games(self) -> list[Game]:
        """Return every game using this video as its archive master."""
        return list(self.game_archive.all())

    def _resolve(self) -> tuple[str, Game | Cut | None]:
        """Return the kind of this video and the object owning it.

        ``game`` and ``cut`` are reverse one-to-one accessors, so ``hasattr``
        answers whether the link exists. ``game_archive`` is a reverse
        foreign key: its manager always exists, only a query tells.
        """
        if hasattr(self, "game"):
            return self.Kind.PROXY, self.game
        if hasattr(self, "cut"):
            return self.Kind.GENERATED_RENDERED, self.cut
        archived_game = self.game_archive.first()
        if archived_game is not None:
            return self.Kind.ARCHIVE, archived_game
        return self.Kind.ORPHAN, None

    @property
    def tournament(self) -> Tournament:
        """Return the tournament this video belongs to."""
        kind, owner = self._resolve()
        if owner is None:
            raise ValueError(f"Video {self.pk} is not linked to a game or a cut")
        if kind == self.Kind.GENERATED_RENDERED:
            return cast("Cut", owner).game.tournament
        return cast("Game", owner).tournament

    @property
    def base_url(self) -> str:
        """Return the base URL for this video."""
        return f"{self.tournament.tournament_media_url}/{self.kind}"

    @property
    def base_path(self) -> Path:
        """Return the base path for this video."""
        return self.tournament.media_path / self.kind


class VideoFileQuerySet(models.QuerySet["VideoFile"]):
    """Queryset helpers for the files backing a video."""

    def for_tournament(self, tournament: Tournament) -> VideoFileQuerySet:
        """Return every file of a tournament, whatever owns its video."""
        return self.filter(
            models.Q(video__game__tournament=tournament)
            | models.Q(video__cut__game__tournament=tournament)
            | models.Q(video__game_archive__tournament=tournament)
        ).distinct()

    def on_disk_pks(self) -> list[int]:
        """Return the pks whose stored path points at a file that exists.

        Existence is a filesystem stat, so it has no SQL equivalent: the
        caller gets primary keys to feed back into a query. Statting the
        whole table costs ~0.7s cold and ~15ms warm, so this is meant to be
        called when sorting or filtering on it, not on every page load.
        """
        return [
            pk
            for pk, path in self.values_list("pk", "path")
            if path and file_exists(path)
        ]


class VideoFile(models.Model):
    """Physical file for a video quality and format."""

    class FileCheck(models.TextChoices):
        """Outcome of :meth:`VideoFile.check_file`."""

        NO_PATH = "no_path", "aucun chemin enregistre"
        MISSING = "missing", "fichier absent du disque"
        PROBE_FAILED = "probe_failed", "ffprobe n'a pas pu lire le fichier"
        PATH_FIXED = "path_fixed", "chemin perime, repare"
        FPS_FILLED = "fps_filled", "fps vide, maintenant renseigne"
        FPS_UPDATED = "fps_updated", "fps errone, corrige"
        OK = "ok", "fichier present, fps deja correct"

    class Quality(models.TextChoices):
        """Available video qualities."""

        LOW = "low", "low"
        MEDIUM = "medium", "medium"
        HIGH = "high", "high"
        LOW_AV1 = "low_av1", "low_av1"
        MEDIUM_AV1 = "medium_av1", "medium_av1"
        HIGH_AV1 = "high_av1", "high_av1"

        ARCHIVE = "archive", "archive"

    class Format(models.TextChoices):
        """Available video formats."""

        MP4 = "mp4", "mp4"

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="files")
    quality = models.CharField(max_length=10, choices=Quality.choices)
    format = models.CharField(
        max_length=10,
        choices=Format.choices,
        default=Format.MP4,
    )
    path = models.CharField(max_length=512)
    size = models.PositiveBigIntegerField(null=True, blank=True)
    fps = models.FloatField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = VideoFileQuerySet.as_manager()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the model."""
        if self.video and not self.path:
            filename = self.video.expected_filename(
                self.quality,
                file_format=self.format,
            )
            self.path = str(self.video.base_path / filename)
        super().save(*args, **kwargs)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_video_file"

    @staticmethod
    def validate_quality(*, quality: str, throw_exception: bool = False) -> bool:
        """Validates the quality of the video file among the available choices."""
        valid_qualities = {choice[0] for choice in VideoFile.Quality.choices}
        quality_exists = quality not in valid_qualities
        if throw_exception and quality_exists:
            raise ValueError(
                f"Quality must be one of: {', '.join(sorted(valid_qualities))}"
            )
        return quality_exists

    @staticmethod
    def validate_format(
        *, file_format: str = "mp4", throw_exception: bool = False
    ) -> bool:
        """Validates the format of the video file among the available choices."""
        valid_formats = {choice[0] for choice in VideoFile.Format.choices}
        format_exists = file_format not in valid_formats
        if throw_exception and format_exists:
            raise ValueError(
                f"Format must be one of: {', '.join(sorted(valid_formats))}"
            )

        return format_exists

    def __str__(self) -> str:
        """Str representation."""
        return f"{self.video} [{self.quality}.{self.format}]"

    @property
    def expected_filename(self) -> str:
        """Return the ideal filename for this video file."""
        return self.video.expected_filename(
            self.quality,
            file_format=self.format,
        )

    def expected_path(self) -> Path:
        """Return the ideal path for this video file."""
        return self.video.base_path / self.expected_filename

    @property
    def exists_on_disk(self) -> bool:
        """Tell whether the stored path points at an existing file."""
        return bool(self.path) and file_exists(self.path)

    @property
    def real_path(self) -> Path:
        """Return the real existing path stored for this file."""
        if not self.path:
            raise FileNotFoundError(f"VideoFile {self.pk} has no stored path.")

        file_path = Path(self.path)
        if not file_exists(file_path):
            raise FileNotFoundError(f"Video file does not exist: {file_path}")

        return file_path

    @property
    def url(self) -> str:
        """Get the url for this video file."""
        try:
            return f"{self.video.base_url}/{ self.real_path.name}"
        except FileNotFoundError:
            return ""

    def set_real_path(self, path: Path) -> None:
        """Persist the real path for this video file."""
        self.path = str(path)
        self.size = path.stat().st_size if file_exists(path) else None
        self.fps = self.probe_fps(path)
        self.save(update_fields=["path", "size", "fps"])

    def check_file(self, *, save: bool = True) -> tuple[str, float | None]:
        """Check the file is on disk, repair a stale path, refresh the fps.

        Returns the :class:`FileCheck` outcome and the probed fps (``None``
        when the file is unusable). A stored fps is never wiped by a failed
        probe: a transient ffprobe or storage error must not destroy a value
        that was right.
        """
        path, relocated = self._locate()
        if path is None:
            return (
                self.FileCheck.MISSING if self.path else self.FileCheck.NO_PATH
            ), None

        updated: list[str] = []
        if relocated:
            self.path = str(path)
            self.size = path.stat().st_size
            updated += ["path", "size"]

        probed = self.probe_fps(path)
        outcome = self._refresh_fps(probed, updated)
        if relocated and outcome != self.FileCheck.PROBE_FAILED:
            # A repaired path is the bigger news than the fps that came with it.
            outcome = self.FileCheck.PATH_FIXED

        if updated and save:
            self.save(update_fields=updated)
        return outcome, probed

    def _refresh_fps(self, probed: float | None, updated: list[str]) -> str:
        """Store the probed frame rate, recording the field it changed."""
        if probed is None:
            return self.FileCheck.PROBE_FAILED
        if self.fps is None:
            outcome = self.FileCheck.FPS_FILLED
        elif abs(self.fps - probed) > FPS_TOLERANCE:
            outcome = self.FileCheck.FPS_UPDATED
        else:
            return self.FileCheck.OK
        self.fps = probed
        updated.append("fps")
        return outcome

    def _locate(self) -> tuple[Path | None, bool]:
        """Return the file backing this row, and whether it had to be found again."""
        if self.path and file_exists(self.path):
            return Path(self.path), False
        for candidate in self._candidate_paths():
            if str(candidate) != self.path and file_exists(candidate):
                return candidate, True
        return None, False

    def _candidate_paths(self) -> list[Path]:
        """Return where the file could be, once the stored path went stale.

        `path` is an absolute snapshot taken at render time. Archiving a
        tournament changes its drive, and renaming a video changes the slug
        in its filename: either leaves the row pointing at nothing while the
        file itself is still there, under the current directory.
        """
        if self.video_id is None:
            return []
        try:
            base = self.video.base_path
            candidates = [base / self.expected_filename]
        except ValueError:
            # An orphan video has no directory to look into.
            return []
        if self.path:
            candidates.append(base / Path(self.path).name)
        return candidates

    @staticmethod
    def probe_fps(path: Path) -> float | None:
        """Read the frame rate of a file, or None if it cannot be determined.

        The front-end converts frames to seconds with this value, so an
        approximation (60 instead of 60000/1001) drifts by seconds over a
        full game. Never fatal: a missing fps only degrades that conversion.
        """
        if not file_exists(path):
            return None
        try:
            return get_fps(path)
        except (
            subprocess.SubprocessError,
            OSError,
            KeyError,
            IndexError,
            ValueError,
        ):
            return None
