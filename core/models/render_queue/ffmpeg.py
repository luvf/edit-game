"""FFmpeg-backed render queue items: shared encoder logic + Cut/Proxy jobs."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, ClassVar

from django.db import models

from core.models.render_queue.base import RenderQueueItemBase
from core.models.video import VideoFile
from edit_game import settings
from jugger_video_manipulation.cut_json_parser import CutJsonParser
from jugger_video_manipulation.ffmpeg_utils import (
    FilterComplexBuilder,
    ffmpeg_command_builder,
    get_fps,
    write_chapters_metadata,
)


class RenderQueueItemFFMPEG(RenderQueueItemBase):
    """Concrete base for ffmpeg-driven jobs; treat `build_command` as abstract."""

    PRESET_ARGS_GPU: ClassVar[dict[str, dict[str, list[str]]]] = {
        "low": {
            "scale": ["854", "-2"],
            "video": [
                "-c:v",
                "h264_nvenc",
                "-cq",
                "35",
                "-preset",
                "p4",
            ],
            "audio": ["-c:a", "aac", "-b:a", "96k"],
        },
        "medium": {
            "scale": ["1280", "-2"],
            "video": ["-c:v", "hevc_nvenc", "-cq", "32", "-preset", "p4"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
        "high": {
            "video": ["-c:v", "hevc_nvenc", "-cq", "18", "-preset", "p4"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
    }
    PRESET_ARGS_CPU: ClassVar[dict[str, dict[str, list[str]]]] = {
        "low": {
            "scale": ["640", "-2"],
            "video": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "35"],
            "audio": ["-c:a", "aac", "-b:a", "96"],
        },
        "medium": {
            "video": ["-c:v", "libx264", "-preset", "medium", "-crf", "23"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
        "high": {
            "video": ["-c:v", "libx264", "-preset", "slow", "-crf", "20"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
        "low_av1": {
            "scale": ["854", "-2"],
            "video": ["-c:v", "libsvtav1", "-crf", "61", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "96k"],
        },
        "medium_av1": {
            "video": ["-c:v", "libsvtav1", "-crf", "55", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "160k"],
        },
        "high_av1": {
            "video": ["-c:v", "libsvtav1", "-crf", "24", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
    }

    preset = models.CharField(max_length=10, default="medium")
    output_filename = models.CharField(max_length=255, blank=True, default="")
    command = models.TextField(blank=True, default="")
    tmp_concat_file = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_ffmpeg"

    @staticmethod
    def _source_has_av1_video(file_path: Path) -> bool:
        """Return True when the source file contains an AV1 video stream."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, OSError):
            return False

        return result.stdout.strip().lower() == "av1"

    def _can_use_cuda_for_decode(self, source_files: list[Path]) -> bool:
        """Return True when CUDA can safely be used for decoding all sources."""
        if not self._is_cuda_available():
            return False

        return not any(
            self._source_has_av1_video(source_file) for source_file in source_files
        )

    def _can_use_cuda_for_encode(self) -> bool:
        """Return True when CUDA can be used for NVENC encoding."""
        return self._is_cuda_available()

    @staticmethod
    def _is_cuda_available() -> bool:
        """Check if CUDA is available."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return False
        try:
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-hwaccels"],
                check=False,
                capture_output=True,
            )
            if result.returncode != 0:
                return False
            return "cuda" in result.stdout.lower().decode("utf-8")
        except (subprocess.CalledProcessError, OSError):
            return False

    @property
    def command_parameters(self) -> str:
        """Return command parameters for the render queue item."""
        return self.command

    @property
    def metadata(self) -> str:
        """Return metadata for this queue item, if any."""
        return self.preset

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Fill output_filename from the renderable when missing."""
        if not self.output_filename:
            with contextlib.suppress(Exception):
                self.output_filename = self.final_output_path.name
        super().save(*args, **kwargs)

    @property
    def final_output_path(self) -> Path:
        """Return the final path where the rendered file must be written."""
        raise NotImplementedError("Use a concrete ffmpeg queue item type.")

    def build_command(
        self,
        chapter_metadata_tmp_path: Path | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ffmpeg command for this queue item."""
        raise NotImplementedError("Use a concrete ffmpeg queue item type.")

    def _execute(self) -> None:
        """Build the ffmpeg command, persist it, then run it."""
        tmp_dir = Path(Path(settings.BASE_DIR) / "tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        tmp_output_path = tmp_dir / f"{uuid.uuid4()}.mp4"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as template_file:
            metadata_path = Path(template_file.name)

        try:
            command = self.build_command(
                chapter_metadata_tmp_path=metadata_path,
                output_file=tmp_output_path,
            )

            update_fields: list[str] = ["command"]
            if self.output_filename:
                update_fields.append("output_filename")
            self.command = " ".join(command)
            self.save(update_fields=update_fields)

            self._run_subprocess(command)

            actual_metadata = self._probe_file(tmp_output_path)
            expected_metadata = self._expected_metadata()

            validation_errors = self._validation_errors(actual_metadata)
            if validation_errors:
                raise ValueError(
                    f"expected : {expected_metadata}... got {actual_metadata}. "
                    f"Validation errors: {', '.join(validation_errors)}"
                )

            final_path = self.final_output_path
            final_path.parent.mkdir(parents=True, exist_ok=True)

            self._move_into_place(tmp_output_path, final_path)

        finally:
            metadata_path.unlink(missing_ok=True)
            tmp_output_path.unlink(missing_ok=True)

    @staticmethod
    def _move_into_place(tmp_path: Path, final_path: Path) -> None:
        """Move the rendered file to its final path.

        tmp_path and final_path can live on different filesystems (e.g. a
        local tmp dir and a network mount), so a plain rename isn't possible.
        Instead, copy to a staging file in final_path's own directory, then
        atomically rename it over final_path. This never truncates/opens
        final_path itself, so an existing file there (e.g. still open for
        reading elsewhere) is only ever swapped out atomically, never
        corrupted mid-write.
        """
        staging_path = final_path.with_name(
            f".{final_path.name}.tmp-{uuid.uuid4().hex}"
        )
        try:
            shutil.copyfile(str(tmp_path), str(staging_path))
            staging_path.replace(final_path)
        finally:
            staging_path.unlink(missing_ok=True)

    def _probe_file(self, file_path: Path) -> Any:
        """Return ffprobe metadata as a dict."""
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _expected_metadata(self) -> dict[str, str]:
        """Return the expected metadata for the generated file."""
        return {
            "preset": self.preset,
        }

    def _validation_errors(self, actual_metadata: dict[str, Any]) -> list[str]:
        """Return the list of validation errors for the generated file."""
        errors: list[str] = []
        minimal_clip_lengh = 5
        format_info = actual_metadata.get("format") or {}
        streams = actual_metadata.get("streams") or []

        format_name = str(format_info.get("format_name", "")).lower()
        if "mp4" not in format_name:
            errors.append(f"format attendu mp4, obtenu {format_name or 'inconnu'}")

        try:
            duration = float(format_info.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0
        if duration <= minimal_clip_lengh:
            errors.append(f"durée attendue > 5s, obtenue {duration}s")

        has_video = any(stream.get("codec_type") == "video" for stream in streams)
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)

        if not has_video:
            errors.append("aucune piste vidéo détectée")
        if not has_audio:
            errors.append("aucune piste audio détectée")

        return errors

    def _preset_args(self) -> dict[str, list[str]]:
        """Return ffmpeg args for the selected preset."""
        default_preset_cpu = list(self.PRESET_ARGS_CPU.keys())[0]
        cpu_preset_args = self.PRESET_ARGS_CPU.get(
            self.preset,
            self.PRESET_ARGS_CPU[default_preset_cpu],
        )

        if not self._is_cuda_available():
            return cpu_preset_args

        return self.PRESET_ARGS_GPU.get(self.preset, cpu_preset_args)

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,  # noqa: FBT001, FBT002
    ) -> tuple[int, dict[str, int]]:
        """Delete the queue item and its tmp concat file, if any."""
        if self.tmp_concat_file:
            concat_path = Path(self.tmp_concat_file)
            with contextlib.suppress(OSError):
                concat_path.unlink()
        return super().delete(using=using, keep_parents=keep_parents)


class RenderQueueItemCut(RenderQueueItemFFMPEG):
    """Queue item for cut renders."""

    cut = models.ForeignKey("core.Cut", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_cut"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches cut renders."""
        self.job_type = self.JobType.CUT_RENDER
        super().save(*args, **kwargs)

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this cut render."""
        self.cut.ensure_video()
        video = self.cut.rendered_video

        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path

    def build_command(
        self,
        chapter_metadata_tmp_path: Path | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ffmpeg command for cut renders.

        First concatenate the input files
        Second split the concatenated file into in-out segments
        Last encode the split file with the selected preset.

        Args:
            chapter_metadata_tmp_path: Path to the temporary metadata file, if any.
            output_file: Path to the output file, if any.

        Return:
            The ffmpeg command for subprocess.
        """
        game = self.cut.game
        out_file = output_file or self.final_output_path
        out_file.parent.mkdir(parents=True, exist_ok=True)

        points, _ = CutJsonParser(self.cut.json_file.path).parse()

        preset_args = self._preset_args()

        source_files = game.get_source_files()
        nb_files = len(source_files)

        fps = get_fps(source_files[0])

        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)
        filter_complex.filter_cut(fps, points)

        scale = preset_args.get("scale")
        if scale:
            w, h = scale
            filter_complex.filter_scale(w, h)

        if chapter_metadata_tmp_path:
            write_chapters_metadata(
                points=points,
                metadata_path=chapter_metadata_tmp_path,
                fps=fps,
            )

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=source_files,
            output_file=out_file,
            chapter_metadata_path=chapter_metadata_tmp_path,
            preset_args=preset_args,
            decode_cuda_available=self._can_use_cuda_for_decode(source_files),
            encode_cuda_available=self._can_use_cuda_for_encode(),
        )
        self.command = " ".join(cmd)
        return cmd


class RenderQueueItemGameRender(RenderQueueItemFFMPEG):
    """Queue item for proxy renders."""

    game = models.ForeignKey("core.Game", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        abstract = True

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this cut render."""
        self.game.ensure_video()
        video = self.game.video_proxy
        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path

    def get_source_files(self) -> list[Path]:
        """Return the source files to consider for encoding.

        If an archive video is set and exists, it will be used as the only source file.
        """
        return self.game.get_source_files()

    def build_command(
        self,
        chapter_metadata_tmp_path: Path | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ffmpeg command for proxy renders.

        concatenate the source files
        and encode them with the selected preset.

        Args:
            chapter_metadata_tmp_path: Path to the temporary metadata file, if any.
            output_file: Path to the output file, if any.

        Returns:
            list of parameters arg for ffmpeg
        """
        _ = chapter_metadata_tmp_path

        out_file = output_file or self.final_output_path
        out_file.parent.mkdir(parents=True, exist_ok=True)

        preset_args = self._preset_args()

        source_files = self.get_source_files()
        nb_files = len(source_files)

        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)

        scale = preset_args.get("scale")
        if scale:
            w, h = scale
            filter_complex.filter_scale(w, h)

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=source_files,
            output_file=out_file,
            preset_args=preset_args,
            decode_cuda_available=self._can_use_cuda_for_decode(source_files),
            encode_cuda_available=self._can_use_cuda_for_encode(),
        )

        self.command = " ".join(cmd)
        return cmd


class RenderQueueItemProxy(RenderQueueItemGameRender):
    """Queue item for proxy renders."""

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_proxy"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches proxy renders."""
        self.job_type = self.JobType.GAME_PROXY
        super().save(*args, **kwargs)

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this proxy render."""
        self.game.ensure_video()
        video = self.game.video_proxy
        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path


class RenderQueueItemArchive(RenderQueueItemGameRender):
    """Queue item for archive renders."""

    DEFAULT_PRESET = "archive"

    PRESET_ARGS_GPU: ClassVar[dict[str, dict[str, list[str]]]] = {}

    PRESET_ARGS_CPU: ClassVar[dict[str, dict[str, list[str]]]] = {
        "archive": {
            "video": ["-c:v", "libsvtav1", "-crf", "34", "-preset", "6"],
            "audio": ["-c:a", "aac", "-b:a", "192k"],
        },
    }

    def _preset_args(self) -> dict[str, list[str]]:
        """Return CPU-only ffmpeg args for archive presets."""
        return self.PRESET_ARGS_CPU.get(
            self.preset,
            self.PRESET_ARGS_CPU[self.DEFAULT_PRESET],
        )

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_archive"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Set archive default preset when no preset is explicitly provided."""
        if not args and "preset" not in kwargs:
            kwargs["preset"] = self.DEFAULT_PRESET
        super().__init__(*args, **kwargs)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches archive renders."""
        self.job_type = self.JobType.GAME_ARCHIVE

        super().save(*args, **kwargs)

    def get_source_files(self) -> list[Path]:
        """Return the source files to consider for encoding.

        If an archive video is set and exists, it will be used as the only source file.
        """
        return self.game.get_source_files(force_rush=True)

    @property
    def final_output_path(self) -> Path:
        """Return the final output path for this archive render."""
        self.game.ensure_archive_video()
        video = self.game.ensure_archive_video()
        video_file, _ = VideoFile.objects.get_or_create(
            video=video,
            quality=self.preset,
            format=VideoFile.Format.MP4,
        )
        final_path = video_file.expected_path()
        video_file.set_real_path(final_path)
        return final_path
