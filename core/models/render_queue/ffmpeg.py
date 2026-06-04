"""FFmpeg-backed render queue items: shared encoder logic + Cut/Proxy jobs."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from django.db import models
from django.utils.text import slugify

from core.models.render_queue.base import RenderQueueItemBase
from jugger_video_manipulation.cut_json_parser import CutJsonParser
from jugger_video_manipulation.ffmpeg_utils import (
    FilterComplexBuilder,
    ffmpeg_command_builder,
    get_fps,
    write_chapters_metadata,
)

if TYPE_CHECKING:
    from core.models.game import RenderableMixin


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
    def _get_renderable(self) -> RenderableMixin:
        """Return the renderable object associated with this queue item."""
        raise NotImplementedError("Use a concrete ffmpeg queue item type.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Fill output_filename from the renderable when missing."""
        if not self.output_filename:
            with contextlib.suppress(Exception):
                self.output_filename = self._get_renderable.rendered_filename(
                    quality=self.preset
                )
        super().save(*args, **kwargs)

    def build_command(self, chapter_metadata_tmp_path: Path | None = None) -> list[str]:
        """Build the ffmpeg command for this queue item."""
        raise NotImplementedError("Use a concrete ffmpeg queue item type.")

    def _execute(self) -> None:
        """Build the ffmpeg command, persist it, then run it."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as template_file:
            metadata_path = Path(template_file.name)
            command = self.build_command(chapter_metadata_tmp_path=metadata_path)

            update_fields: list[str] = ["command"]
            if self.output_filename:
                update_fields.append("output_filename")
            self.save(update_fields=update_fields)
        try:
            self._run_subprocess(command)
        finally:
            metadata_path.unlink(missing_ok=True)

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
    def _get_renderable(self) -> RenderableMixin:
        """Return the renderable object associated with this queue item."""
        return self.cut

    def build_command(self, chapter_metadata_tmp_path: Path | None = None) -> list[str]:
        """Build the ffmpeg command for cut renders.

        First concatenate the input files
        Second split the concatenated file into in-out segments
        Last encode the split file with the selected preset.

        :returns: The ffmpeg command for subprocess.
        """
        game = self.cut.game
        input_dir = Path(game.tournament.source_dir)
        out_file = self._get_renderable.rendered_path(quality=self.preset)
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

    def build_out_filename(self) -> str:
        """Build the output filename for proxy renders."""
        stem = slugify(Path(self.game.files[0]).stem)
        return f"{stem}_{self.preset}.mp4"

    @property
    def _get_renderable(self) -> RenderableMixin:
        """Return the renderable object associated with this queue item."""
        return self.game

    def build_command(self, chapter_metadata_tmp_path: Path | None = None) -> list[str]:
        """Build the ffmpeg command for proxy renders.

        concatenate the source files
        and encode them with the selected preset.

        Args:
            chapter_metadata_tmp_path: Path to the temporary metadata file, if any.

        Returns:
            list of parameters arg for ffmpeg
        """
        _ = chapter_metadata_tmp_path
        if not self.output_filename:
            self.output_filename = self._get_renderable.rendered_filename(
                quality=self.preset
            )
        input_dir = Path(self.game.tournament.source_dir)
        out_file = self._get_renderable.rendered_path(quality=self.preset)
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
