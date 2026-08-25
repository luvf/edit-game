"""Game model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ValidationError
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
        self, *, preset: str = "high", force: bool = False
    ) -> RenderQueueItemArchive:
        """Create a render queue item to generate the game archive."""
        from core.models.render_queue.ffmpeg import RenderQueueItemArchive

        if not force and self.archive_video:
            try:
                path = self.archive_video.path_for_quality("archive")
            except FileNotFoundError:
                pass
            else:
                if path.exists():
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
