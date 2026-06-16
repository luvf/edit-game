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

    RUSH_DIRNAME = "rushs"
    PROXY_DIRNAME = "proxy"
    GENERATED_RENDERED_DIRNAME = "generated_rendered"

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
    }

    preset = models.CharField(max_length=10, default="medium")
    output_filename = models.CharField(max_length=255, blank=True, default="")
    command = models.TextField(blank=True, default="")
    tmp_concat_file = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_ffmpeg"

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

            shutil.move(str(tmp_output_path), str(final_path))

        finally:
            metadata_path.unlink(missing_ok=True)
            tmp_output_path.unlink(missing_ok=True)

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
        if self._is_cuda_available():
            return self.PRESET_ARGS_GPU.get(self.preset, self.PRESET_ARGS_GPU["medium"])
        return self.PRESET_ARGS_CPU.get(self.preset, self.PRESET_ARGS_CPU["medium"])

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
        input_dir = game.tournament.media_path
        out_file = output_file or self.final_output_path
        out_file.parent.mkdir(parents=True, exist_ok=True)

        points, _ = CutJsonParser(self.cut.json_file.path).parse()

        preset_args = self._preset_args()
        nb_files = len(game.files)
        fps = get_fps(input_dir / self.RUSH_DIRNAME / game.files[0])

        w, h = preset_args["scale"]
        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)
        filter_complex.filter_cut(fps, points)
        filter_complex.filter_scale(w, h)
        if chapter_metadata_tmp_path:
            write_chapters_metadata(
                points=points,
                metadata_path=chapter_metadata_tmp_path,
                fps=fps,
            )

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=[(input_dir / self.RUSH_DIRNAME / f) for f in game.files],
            output_file=out_file,
            chapter_metadata_path=chapter_metadata_tmp_path,
            preset_args=preset_args,
            cuda_available=self._is_cuda_available(),
        )
        self.command = " ".join(cmd)
        return cmd


class RenderQueueItemProxy(RenderQueueItemFFMPEG):
    """Queue item for proxy renders."""

    game = models.ForeignKey("core.Game", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_proxy"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches proxy renders."""
        self.job_type = self.JobType.GAME_PROXY
        super().save(*args, **kwargs)

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

        input_dir = self.game.tournament.media_path
        out_file = output_file or self.final_output_path
        out_file.parent.mkdir(parents=True, exist_ok=True)

        preset_args = self._preset_args()
        nb_files = len(self.game.files)

        w, h = preset_args["scale"]

        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)
        filter_complex.filter_scale(w, h)

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=[(input_dir / self.RUSH_DIRNAME / f) for f in self.game.files],
            output_file=out_file,
            preset_args=preset_args,
            cuda_available=self._is_cuda_available(),
        )

        self.command = " ".join(cmd)
        return cmd


class RenderQueueItemArchive(RenderQueueItemFFMPEG):
    """Queue item for archive renders."""

    game = models.ForeignKey("core.Game", on_delete=models.CASCADE)
