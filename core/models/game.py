"""Game model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import OneToOneField

if TYPE_CHECKING:
    from core.models.render_queue.ffmpeg import (
        RenderQueueItemArchive,
        RenderQueueItemProxy,
    )
    from core.models.video import Video


class ArchiveAlreadyExistsError(ValidationError):
    """Raised when an archive render is requested but one already exists or is pending."""

    def __init__(self, message: str, archive_video_id: int | None) -> None:
        """Initialize with the conflicting archive video's id, if any."""
        super().__init__(message)
        self.archive_video_id = archive_video_id


# The render qualities a thumbnail is best taken from, best first.
MINIATURE_QUALITIES = (
    "youtube",
    "high",
    "high_av1",
    "medium",
    "medium_av1",
    "low",
    "low_av1",
)


class Game(models.Model):
    """Game model."""

    name = models.CharField(max_length=100)
    files = models.JSONField("Files")
    tournament = models.ForeignKey("core.Tournament", on_delete=models.CASCADE)
    team1 = models.ForeignKey(
        "core.Team", on_delete=models.SET_NULL, related_name="game_team1", null=True
    )
    team2 = models.ForeignKey(
        "core.Team", on_delete=models.SET_NULL, related_name="game_team2", null=True
    )
    # What the match is, shared by every cut of it: the render reads these for
    # the opening card and the scoreboard. `team1` is the team on the left at
    # kick-off, which is what tells the board whose point a `left` is.
    condition = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Condition de victoire, en texte libre, affichée sur la carte d'ouverture.",
    )
    sets_to_win = models.PositiveSmallIntegerField(null=True, blank=True)
    start_score = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Score quand l'enregistrement commence, pour un match déjà en cours : "
            '{"team1": [10, 3], "team2": [8, 0]}, un nombre par set, le dernier '
            "étant le set en cours."
        ),
    )

    # Where the match sits in the schedule: its terrain, its day, and its
    # place in that day. Together they make the game's number, TTJGG.
    field_number = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(99)],
        help_text="Numéro de terrain, sur 2 chiffres.",
    )
    day_number = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(9)],
        help_text="Numéro de jour, sur 1 chiffre.",
    )
    game_number = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(99)],
        help_text="Numéro de la game dans la journée, sur 2 chiffres.",
    )
    win_condition = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Condition de victoire en code court, comme 1a10+2v : elle entre dans le nom des rendus.",
    )

    json_file = models.FileField(upload_to="json_files", default="tt")
    slug = models.SlugField(default="", null=False)
    video_proxy = OneToOneField(
        "core.Video",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="game",
    )
    archive_video = models.ForeignKey(
        "core.Video",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="game_archive",
        help_text="Vidéo haute qualité utilisée comme archive/master pour les encodages de ce match.",
    )
    # The thumbnail and YouTube metadata of this match. A VideoMetadata no game
    # points at still works: it reads its video from the rendered dir.
    video_metadata = OneToOneField(
        "core.VideoMetadata",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="game",
    )

    class Meta:
        """Model metadata."""

        db_table = "game_edit_game"

    @property
    def json_file_path(self) -> Path:
        """Get the path to the json file."""
        return Path(self.json_file.path)

    def __str__(self) -> str:
        """To string representation."""
        return self.name

    @property
    def number(self) -> str:
        """Return the game's number, TTJGG: terrain, day, game of the day."""
        return f"{self.field_number:02d}{self.day_number}{self.game_number:02d}"

    def ensure_archive_video(self) -> Video:
        """Ensure this game has an archive video object and return it."""
        from core.models.video import Video

        if self.archive_video:
            return self.archive_video

        video = Video.objects.create(
            name=f"archive{self.name}",
        )

        self.archive_video = video
        self.save(update_fields=["archive_video"])

        return video

    def get_source_files(self, *, force_rush: bool = False) -> list[Path]:
        """Retuns the source files to consider for encoding.

        If an archive video is set and exists, it will be used as the only source
        file, unless force_rush is set and the rush files are available, in which
        case the rush files are used instead.
        """
        base_path = Path(self.tournament.media_path) / "rushs"
        rush_files = [base_path / f for f in self.files]

        if force_rush and all(f.exists() for f in rush_files):
            return rush_files

        if self.archive_video:
            try:
                return [self.archive_video.path_for_quality("archive")]
            except FileNotFoundError:
                pass

        return rush_files

    def get_miniature_source(self) -> Path:
        """Return the video a thumbnail frame and its chapters are read from.

        A cut render comes first: it is what gets published, so its frames and
        chapters are those of the video on YouTube. The latest cut wins, and in
        it the best quality on disk. Without any render, the archive then the
        proxy still give a frame of the match, without chapters.

        Raises:
        - FileNotFoundError if none of the game's videos has a file on disk.
        """
        from core.models.video import VideoFile, file_exists

        quality_rank = {
            quality: rank for rank, quality in enumerate(MINIATURE_QUALITIES)
        }
        renders = sorted(
            VideoFile.objects.filter(video__cut__game=self).values_list(
                "video__cut__pk", "quality", "path"
            ),
            key=lambda row: (-row[0], quality_rank.get(row[1], len(quality_rank))),
        )
        candidates = [path for _, _, path in renders]
        for video in (self.archive_video, self.video_proxy):
            if video is not None:
                candidates += [video_file.path for video_file in video.files.all()]

        for path in candidates:
            if path and file_exists(path):
                return Path(path)
        raise FileNotFoundError(f"Game {self.pk} has no video file on disk.")

    def has_youtube_render(self) -> bool:
        """Tell whether one of this game's cuts has a YouTube render on disk.

        It is the video that gets published, so the only one worth a thumbnail
        and a description. The file row is created when the render starts, so
        the disk is what says the render is done.
        """
        from core.models.video import VideoFile, file_exists

        return any(
            file_exists(path)
            for path in VideoFile.objects.filter(
                video__cut__game=self, quality=VideoFile.Quality.YOUTUBE
            ).values_list("path", flat=True)
            if path
        )

    def has_archive_on_disk(self) -> bool:
        """Tell whether this game already has an archive file on disk.

        Any file attached to the archive video counts, whatever quality it is
        filed under. A game has one archive; the quality label only records
        which preset produced it, and renders enqueued by the batch command
        used to be filed as "high" while everything else used "archive".
        Looking at one label only made a game with the other look unarchived,
        which is how some games ended up with two.
        """
        if not self.archive_video:
            return False

        return any(
            video_file.exists_on_disk for video_file in self.archive_video.files.all()
        )

    def ensure_video(self) -> None:
        """Create and attach a video if missing."""
        if self.video_proxy:
            return
        from core.models.video import Video

        self.video_proxy = Video.objects.create(name=self.name)
        self.save(update_fields=["video_proxy"])

    def get_json(self) -> dict[str, Any]:
        """Get the json file as a dict."""
        with self.json_file_path.open() as f:
            return cast(dict[str, Any], json.load(f))

    def set_json(self, json_data: dict[str, Any]) -> None:
        """Set the json file."""
        with self.json_file_path.open("w") as f:
            json.dump(json_data, f, indent=4)

    def enqueue_proxy_render(
        self,
        preset: str = "low",
    ) -> RenderQueueItemProxy:
        """Create a proxy render queue item handled by RenderQueueItemProxy.

        Behavior:
        - Always creates a queue item; rendering happens in the worker.
        - The queue item handles file generation and linking during execution.

        Raises:
        - ValueError if the preset is invalid or if no source files are available.
        """
        from core.models.render_queue.ffmpeg import RenderQueueItemProxy

        if preset not in ["low", "medium", "high", "low_av1", "medium_av1", "high_av1"]:
            raise ValueError("Preset must be low, medium or high")
        self.ensure_video()

        return RenderQueueItemProxy.objects.create(
            game=self,
            preset=preset,
            status=RenderQueueItemProxy.Status.CREATED,
        )

    def enqueue_archive_render(
        self, *, preset: str | None = None, force: bool = False
    ) -> RenderQueueItemArchive:
        """Create a render queue item to generate the game archive.

        `preset` names an archive preset; it also becomes the VideoFile
        quality the result is filed under, so it must be one the archive
        knows. None means the archive default.
        """
        from core.models.render_queue.ffmpeg import RenderQueueItemArchive

        preset = preset or RenderQueueItemArchive.DEFAULT_PRESET

        if not force and self.archive_video and self.has_archive_on_disk():
            raise ArchiveAlreadyExistsError(
                "This game already has an archive. Use force=true to regenerate it.",
                self.archive_video_id,
            )

        existing_item = (
            RenderQueueItemArchive.objects.filter(
                game=self,
                preset=preset,
            )
            .exclude(
                status__in=[
                    RenderQueueItemArchive.Status.DONE,
                    RenderQueueItemArchive.Status.FAILED,
                ],
            )
            .first()
        )

        if existing_item and not force:
            raise ArchiveAlreadyExistsError(
                "A render queue item for this game and preset already exists. Use force=true to create a new one.",
                self.archive_video_id,
            )
        return RenderQueueItemArchive.objects.create(
            game=self,
            preset=preset,
            status=RenderQueueItemArchive.Status.CREATED,
        )
