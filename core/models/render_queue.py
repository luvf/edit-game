"""Render queue models."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from jugger_video_manipulation.cut_json_parser import CutJsonParser
from jugger_video_manipulation.ffmpeg_utils import (
    FilterComplexBuilder,
    ffmpeg_command_builder,
    get_fps,
)

if TYPE_CHECKING:
    from core.models.cut import Cut
    from core.models.game import Game


class RenderQueueItem(models.Model):
    """Queue item for cut renders."""

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

    class JobType(models.TextChoices):
        """Job types for queue items."""

        CUT_RENDER = "CUT_RENDER", "cut_render"
        GAME_PROXY = "GAME_PROXY", "game_proxy"

    class Status(models.TextChoices):
        """Status values for queue items."""

        CREATED = "CREATED", "created"
        WAITING = "WAITING", "waiting"
        RUNNING = "RUNNING", "running"
        DONE = "DONE", "done"
        FAILED = "FAILED", "failed"

    job_type = models.CharField(
        max_length=20, choices=JobType.choices, default=JobType.CUT_RENDER
    )
    preset = models.CharField(max_length=10, default="medium")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CREATED
    )
    output_filename = models.CharField(max_length=255, blank=True, default="")
    command = models.TextField(blank=True, default="")
    tmp_concat_file = models.CharField(max_length=255, blank=True, default="")
    pid = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue"
        ordering: ClassVar[list[str]] = ["created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["status"],
                condition=Q(status="RUNNING"),
                name="renderqueue_single_running",
            )
        ]

    def __str__(self) -> str:
        """To string representation."""
        if self.job_type == self.JobType.GAME_PROXY:
            game = self.game
            label = game.name if game else "unknown game"
        else:
            cut = self.cut
            label = cut.name if cut else "unknown cut"
        return f"{label} [{self.status}]"

    def resolved_output_filename(self) -> str:
        """Compute the output filename if not set."""
        if self.output_filename:
            return self.output_filename
        return self.build_out_filename()

    def build_out_filename(self) -> str:
        """Build the output filename (default: empty)."""
        return ""

    @property
    def base_path(self) -> Path:
        """Base path for output files."""
        return Path()

    def full_output_path(self) -> Path:
        """Return the full output path."""
        return self.base_path / self.output_filename

    def media_path(self) -> Path:
        """Return the MEDIA_ROOT path for this queue item."""
        return Path(settings.MEDIA_ROOT)

    @property
    def cut(self) -> Cut | None:
        """Return the cut for cut render items."""
        try:
            return self.renderqueueitemcut.cut
        except ObjectDoesNotExist:
            return None

    @property
    def game(self) -> Game | None:
        """Return the game for proxy render items."""
        try:
            return self.renderqueueitemproxy.game
        except ObjectDoesNotExist:
            return None

    def build_command(self) -> list[str]:
        """Build the ffmpeg command for this queue item."""
        raise NotImplementedError("Use a concrete queue item type.")

    def concrete(self) -> RenderQueueItem:
        """Return the concrete queue item instance."""
        if self.job_type == self.JobType.CUT_RENDER:
            return RenderQueueItemCut.objects.get(pk=self.pk)
        if self.job_type == self.JobType.GAME_PROXY:
            return RenderQueueItemProxy.objects.get(pk=self.pk)
        raise ValueError(f"Unsupported job type: {self.job_type}")

    def _run_command(self, command: list[str]) -> None:
        """Run the ffmpeg command and handle PID tracking."""
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.pid = process.pid
        self.save(update_fields=["pid"])
        stdout, stderr = process.communicate()

        returncode = process.returncode
        self.pid = None
        self.save(update_fields=["pid"])
        if returncode != 0:
            details = (stderr or stdout or "").strip()
            if details:
                raise RuntimeError(f"ffmpeg failed (code {returncode}): {details}")
            raise RuntimeError(f"ffmpeg failed with code {returncode}.")

    def run(self) -> None:
        """Execute the render for this queue item."""
        command = self.build_command()
        update_fields: list[str] = ["command"]
        if self.output_filename:
            update_fields.append("output_filename")
        self.save(update_fields=update_fields)
        self._run_command(command)
        self._link_storage_symlink()

    def _build_concat_file(self, input_dir: Path, source_files: list[str]) -> Path:
        """Create a concat file in tmp and store its path."""
        self._validate_sources(input_dir, source_files)
        tmp_dir = Path(settings.BASE_DIR) / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        concat_file = tmp_dir / f"concat_sources_{uuid.uuid4().hex}.txt"
        with concat_file.open("w") as f:
            for src in source_files:
                src_path = str((input_dir / "rushs" / Path(src)).absolute())
                escaped = src_path.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        self.tmp_concat_file = str(concat_file)
        return concat_file

    @staticmethod
    def _validate_sources(input_dir: Path, source_files: list[str]) -> None:
        """Validate source files exist and are readable by ffprobe."""
        ffprobe_path = shutil.which("ffprobe")
        bad_files: list[str] = []
        for src in source_files:
            src_path = (input_dir / "rushs" / Path(src)).absolute()
            if not src_path.exists():
                bad_files.append(f"{src_path} (missing)")
                continue
            if not ffprobe_path:
                continue
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(src_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                bad_files.append(f"{src_path} (ffprobe failed)")
        if bad_files:
            details = "; ".join(bad_files)
            raise RuntimeError(f"Invalid source files: {details}")

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

    def _link_storage_symlink(self) -> None:
        """Link full_output_path to media_path/output_filename."""
        source_path = self.full_output_path()
        if not source_path.exists():
            raise FileNotFoundError(f"Render introuvable: {source_path}")
        destination = self.media_path() / Path(self.output_filename).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        os.symlink(source_path, destination)

    def reset(self) -> None:
        """Reset the queue item to created."""
        if self.pid:
            self._terminate_pid(self.pid)
            self.pid = None
        self.status = self.Status.CREATED
        self.started_at = None
        self.finished_at = None
        self.error = ""
        self.save(update_fields=["status", "started_at", "finished_at", "error", "pid"])

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        """Terminate a process by pid."""
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        time.sleep(0.2)
        try:
            os.kill(pid, 0)
        except OSError:
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def run_now(self) -> None:
        """Queue the job for the worker to execute."""
        if self.status == self.Status.RUNNING:
            raise ValueError("Job already running")
        self.status = self.Status.WAITING
        self.started_at = None
        self.finished_at = None
        self.error = ""
        self.save(update_fields=["status", "started_at", "finished_at", "error"])

    def _other_job_running(self) -> bool:
        """Check if another render queue job is already running."""
        return (
            RenderQueueItem.objects.filter(status=self.Status.RUNNING)
            .exclude(pk=self.pk)
            .exists()
        )

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,  # noqa: FBT001, FBT002
    ) -> tuple[int, dict[str, int]]:
        """Delete the queue item and its concat file, if any."""
        if self.tmp_concat_file:
            concat_path = Path(self.tmp_concat_file)
            with contextlib.suppress(OSError):
                concat_path.unlink()
        return super().delete(using=using, keep_parents=keep_parents)


class RenderQueueItemCut(RenderQueueItem):
    """Queue item for cut renders."""

    cut = models.ForeignKey("core.Cut", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_cut"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches cut renders."""
        self.job_type = self.JobType.CUT_RENDER
        if not self.output_filename:
            self.output_filename = self.build_out_filename()
        super().save(*args, **kwargs)

    def _require_game(self) -> Game:
        """Return the cut's game or raise if missing."""
        if not self.cut.game:
            raise ValueError("Cut has no game associated.")
        return self.cut.game

    def build_out_filename(self) -> str:
        """Build the output filename for cut renders."""
        game = self._require_game()
        stem = slugify(Path(game.files[0]).stem)
        cut_name = slugify(self.cut.name)
        return f"{stem}_{cut_name}_{self.preset}.mp4"

    def media_path(self) -> Path:
        """Return the MEDIA_ROOT path for cut renders."""
        return Path(settings.MEDIA_ROOT) / "rendered"

    def build_command(self) -> list[str]:
        """Build the ffmpeg command for cut renders.

        First concatenate the input files
        Second split the concatenated file into in-out segments
        Last encode the split file with the selected preset.

        :returns: The ffmpeg command for subprocess.
        """
        game = self._require_game()
        input_dir = Path(game.tournament.source_dir)
        out_file = self.full_output_path()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        points, _ = CutJsonParser(self.cut.json_file.path).parse()

        preset_args = self._preset_args()
        nb_files = len(game.files)
        fps = get_fps(input_dir / "rushs" / game.files[0])

        w, h = preset_args["scale"]
        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)
        filter_complex.filter_cut(fps, points)
        filter_complex.filter_scale(w, h)

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=[(input_dir / "rushs" / f) for f in game.files],
            output_file=out_file,
            preset_args=preset_args,
            cuda_available=self._is_cuda_available(),
        )
        self.command = " ".join(cmd)
        return cmd

    def _link_storage_symlink(self) -> None:
        """Link render output and update cut metadata."""
        super()._link_storage_symlink()
        if self.cut:
            destination = self.media_path() / Path(self.output_filename).name
            self.cut.rendered_video = str(Path("rendered") / destination.name)
            self.cut.save(update_fields=["rendered_video"])

    @property
    def base_path(self) -> Path:
        """Base path for cut renders."""
        game = self._require_game()
        return Path(game.tournament.source_dir) / "rendered"


class RenderQueueItemProxy(RenderQueueItem):
    """Queue item for proxy renders."""

    game = models.ForeignKey("core.Game", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_proxy"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches proxy renders."""
        self.job_type = self.JobType.GAME_PROXY
        if not self.output_filename:
            self.output_filename = self.build_out_filename()
        super().save(*args, **kwargs)

    def build_out_filename(self) -> str:
        """Build the output filename for proxy renders."""
        stem = slugify(Path(self.game.files[0]).stem)
        return f"{stem}_{self.preset}.mp4"

    def media_path(self) -> Path:
        """Return the MEDIA_ROOT path for proxy renders."""
        return Path(settings.MEDIA_ROOT) / "proxy"

    def build_command(self) -> list[str]:
        """Build the ffmpeg command for proxy renders.

        concatenate the source files
        and encode them with the selected preset.
        :returns
            list of parameters arg for ffmpeg
        """
        if not self.output_filename:
            self.output_filename = self.build_out_filename()
        input_dir = Path(self.game.tournament.source_dir)
        out_file = self.full_output_path()
        out_file.parent.mkdir(parents=True, exist_ok=True)

        preset_args = self._preset_args()
        nb_files = len(self.game.files)

        w, h = preset_args["scale"]

        filter_complex = FilterComplexBuilder(nb_files)
        filter_complex.filter_concat(filter_complex.inputs_v, filter_complex.inputs_a)
        filter_complex.filter_scale(w, h)

        cmd = ffmpeg_command_builder(
            filter_complex=filter_complex,
            input_files=[(input_dir / "rushs" / f) for f in self.game.files],
            output_file=out_file,
            preset_args=preset_args,
            cuda_available=self._is_cuda_available(),
        )

        self.command = " ".join(cmd)
        return cmd

    def _link_storage_symlink(self) -> None:
        """Link proxy output and update game metadata."""
        super()._link_storage_symlink()
        destination = self.media_path() / Path(self.output_filename).name
        proxy_name = str(destination.relative_to(Path(settings.MEDIA_ROOT)))
        if self.game.source_proxy:
            self.game.source_proxy.delete(save=False)
        self.game.source_proxy.name = proxy_name
        self.game.save(update_fields=["source_proxy"])

    @property
    def base_path(self) -> Path:
        """Base path for proxy renders."""
        return Path(self.game.tournament.source_dir) / "proxy"
