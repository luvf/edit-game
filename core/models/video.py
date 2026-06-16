"""Logical video asset."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from django.db import models
from django.utils.text import slugify


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
    def base_url(self) -> str:
        """Return the base URL for this video."""
        if hasattr(self, "game"):
            subdir = "proxy"
            tournament = self.game.tournament
        elif hasattr(self, "cut"):
            subdir = "generated_rendered"
            tournament = self.cut.game.tournament
        else:
            raise ValueError("Video is not linked to a game or a cut")
        return f"{tournament.tournament_media_url}/{subdir}"

    @property
    def base_path(self) -> Path:
        """Return the base path for this video."""
        if hasattr(self, "game"):
            subdir = "proxy"
            tournament = self.game.tournament
        elif hasattr(self, "cut"):
            subdir = "generated_rendered"
            tournament = self.cut.game.tournament
        else:
            raise ValueError("Video is not linked to a game or a cut")
        return tournament.media_path / subdir


class VideoFile(models.Model):
    """Physical file for a video quality and format."""

    class Quality(models.TextChoices):
        """Available video qualities."""

        LOW = "low", "low"
        MEDIUM = "medium", "medium"
        HIGH = "high", "high"

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
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

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
    def real_path(self) -> Path:
        """Return the real existing path stored for this file."""
        if not self.path:
            raise FileNotFoundError(f"VideoFile {self.pk} has no stored path.")

        file_path = Path(self.path)
        if not file_path.exists():
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
        self.size = path.stat().st_size if path.exists() else None
        self.save(update_fields=["path", "size"])
