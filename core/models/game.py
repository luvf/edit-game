"""Game, cut, and render queue models."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar, cast

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Q

from jugger_video_manipulation.cut_json_parser import CutJsonParser


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
    rendered = models.CharField(max_length=200, blank=True)
    json_file = models.FileField(upload_to="json_files", default="tt")
    source_proxy = models.FileField(upload_to="core/previews", default="", blank=True)
    slug = models.SlugField(default="", null=False)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_game"

    @property
    def json_file_path(self) -> Path:
        """Get the path to the json file."""
        return Path(self.json_file.path)

    @property
    def source_proxy_path(self) -> Path:
        """Get the path to the source proxy file."""
        return Path(self.source_proxy.path)

    def __str__(self) -> str:
        """To string representation."""
        return self.name

    def get_json(self) -> dict[str, Any]:
        """Get the json file as a dict."""
        with self.json_file_path.open() as f:
            return cast(dict[str, Any], json.load(f))

    def set_json(self, json_data: dict[str, Any]) -> None:
        """Set the json file."""
        with self.json_file_path.open("w") as f:
            json.dump(json_data, f, indent=4)

    def generate_proxy(
        self,
        preset: str = "low",
        *,
        overwrite: bool = False,
        to_queue: bool = False,
    ) -> RenderQueueItem:
        """Create a proxy render queue item handled by RenderQueueItemProxy.

        Behavior:
        - Always creates a queue item; rendering happens in the worker.
        - The queue item handles file generation and linking during execution.

        Raises:
        - ValueError if the preset is invalid or if no source files are available.
        """
        if preset not in ["low", "medium", "high"]:
            raise ValueError("Preset must be low, medium or high")

        item = RenderQueueItemProxy.objects.create(
            game=self,
            preset=preset,
        )
        if not to_queue:
            item.run()
        else:
            item.status = RenderQueueItem.Status.CREATED
            item.save(update_fields=["status"])
        _ = overwrite
        return item


class Cut(models.Model):
    """Cut model, represents a cut directives to edit the video."""

    CUT_TYPES: ClassVar[list[tuple[str, str]]] = [
        ("MAN", "manual"),
        ("VID", "from video"),
        ("XML", "from XML"),
        ("ML", "from ML"),
        ("X", "others"),
    ]
    name = models.CharField(max_length=100)
    type_cut = models.CharField(max_length=50, choices=CUT_TYPES)
    json_file = models.FileField(
        upload_to="json_files/cuts/", default="json_files/cuts/default.json"
    )
    rendered_video = models.CharField(max_length=255, blank=True, default="")
    slug = models.SlugField(default="", null=False)
    game = models.ForeignKey(Game, on_delete=models.SET_NULL, null=True)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_cut"

    def __str__(self) -> str:
        """To string representation."""
        return self.name

    @property
    def json_file_path(self) -> Path:
        """Get the path to the cut json file."""
        return Path(self.json_file.path)

    def get_json(self) -> dict[str, Any]:
        """Get the cut json file as a dict."""
        with self.json_file_path.open() as f:
            return cast(dict[str, Any], json.load(f))

    def render(self, *, preset: str = "medium") -> RenderQueueItemCut:
        """Create a queue item for this cut render."""
        item = self.to_queue(preset=preset)
        item.run()
        return item

    def to_queue(self, *, preset: str = "medium") -> RenderQueueItemCut:
        """Create a queue item for this cut render."""
        return RenderQueueItemCut.objects.create(
            cut=self,
            preset=preset,
        )


class RenderQueueItem(models.Model):
    """Queue item for cut renders."""

    PRESET_ARGS: ClassVar[dict[str, str]] = {
        "low": "-c:v libx265 -preset fast -crf 32 -vf scale=640x360 -ar 16000",
        "medium": "-c:v libx265 -preset medium -crf 23",
        "high": "-c:v libx265 -preset slow -x265-params lossless=1 -vf scale=3840:2160",
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

    def build_command(self) -> str:
        """Build the ffmpeg command for this queue item."""
        raise NotImplementedError("Use a concrete queue item type.")

    def concrete(self) -> RenderQueueItem:
        """Return the concrete queue item instance."""
        if self.job_type == self.JobType.CUT_RENDER:
            return RenderQueueItemCut.objects.get(pk=self.pk)
        if self.job_type == self.JobType.GAME_PROXY:
            return RenderQueueItemProxy.objects.get(pk=self.pk)
        raise ValueError(f"Unsupported job type: {self.job_type}")

    def _run_command(self, command: str) -> None:
        """Run the ffmpeg command and handle PID tracking."""
        process = subprocess.Popen(command, shell=True)
        self.pid = process.pid
        self.save(update_fields=["pid"])
        returncode = process.wait()
        self.pid = None
        self.save(update_fields=["pid"])
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, command)

    def run(self) -> None:
        """Execute the render for this queue item."""
        command = self.build_command()
        update_fields: list[str] = ["tmp_concat_file", "command"]
        if self.output_filename:
            update_fields.append("output_filename")
        self.save(update_fields=update_fields)
        self._run_command(command)
        self._link_storage_symlink()

    def _build_concat_file(self, input_dir: Path, source_files: list[str]) -> Path:
        """Create a concat file in tmp and store its path."""
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

    def _preset_args(self) -> str:
        """Return ffmpeg args for the selected preset."""
        return self.PRESET_ARGS.get(self.preset, self.PRESET_ARGS["medium"])

    def _hwaccel_args(self) -> str:
        """Return ffmpeg hwaccel args when CUDA is available."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return ""
        try:
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-hwaccels"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return ""
        return "-hwaccel cuda" if "cuda" in result.stdout else ""

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

    cut = models.ForeignKey(Cut, on_delete=models.CASCADE)

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
        stem = Path(game.files[0]).stem
        return f"{stem}_{self.cut.name}_{self.preset}.mp4"

    @property
    def base_path(self) -> Path:
        """Base path for cut renders."""
        game = self._require_game()
        return Path(game.tournament.source_dir) / "rendered"

    def media_path(self) -> Path:
        """Return the MEDIA_ROOT path for cut renders."""
        return Path(settings.MEDIA_ROOT) / "rendered"

    def build_command(self) -> str:
        """Build the ffmpeg command for cut renders."""
        game = self._require_game()
        input_dir = Path(game.tournament.source_dir)
        out_file = self.full_output_path()
        out_file.parent.mkdir(parents=True, exist_ok=True)

        concat_file = self._build_concat_file(input_dir, game.files)

        preset_args = self._preset_args()

        hwaccel = self._hwaccel_args()

        parser = CutJsonParser(self.cut.json_file.path)
        points, _ = parser.parse()
        if points:
            selectors = [
                f"between(n\\,{point['in']}\\,{point['out']})" for point in points
            ]
            select_expr = "+".join(selectors)
            vf = f"select='{select_expr}',setpts=N/FRAME_RATE/TB"
            self.command = (
                f"ffmpeg {hwaccel} -y -f concat -safe 0 -i {concat_file} "
                f'-vf "{vf}" {preset_args} {out_file}'
            )
            return self.command
        self.command = (
            f"ffmpeg {hwaccel} -y -f concat -safe 0 -i {concat_file} "
            f"{preset_args} {out_file}"
        )
        return self.command

    def _link_storage_symlink(self) -> None:
        """Link render output and update cut metadata."""
        super()._link_storage_symlink()
        if self.cut:
            destination = self.media_path() / Path(self.output_filename).name
            self.cut.rendered_video = str(Path("rendered") / destination.name)
            self.cut.save(update_fields=["rendered_video"])


class RenderQueueItemProxy(RenderQueueItem):
    """Queue item for proxy renders."""

    PRESET_ARGS: ClassVar[dict[str, str]] = {
        "low": (
            "-c:v h264_nvenc -preset fast -rc vbr -b:v 2M -maxrate 3M "
            "-bufsize 6M -vf scale=-2:360 -pix_fmt yuv420p "
            "-c:a aac -b:a 96k -movflags +faststart"
        ),
        "medium": (
            "-c:v h264_nvenc -preset fast -rc vbr -b:v 4M -maxrate 6M "
            "-bufsize 12M -vf scale=-2:540 -pix_fmt yuv420p "
            "-c:a aac -b:a 128k -movflags +faststart"
        ),
        "high": (
            "-c:v h264_nvenc -preset fast -rc vbr -b:v 6M -maxrate 8M "
            "-bufsize 16M -vf scale=-2:720 -pix_fmt yuv420p "
            "-c:a aac -b:a 160k -movflags +faststart"
        ),
    }

    game = models.ForeignKey(Game, on_delete=models.CASCADE)

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
        stem = Path(self.game.files[0]).stem
        return f"{stem}_{self.preset}.mp4"

    @property
    def base_path(self) -> Path:
        """Base path for proxy renders."""
        return Path(self.game.tournament.source_dir) / "proxy"

    def media_path(self) -> Path:
        """Return the MEDIA_ROOT path for proxy renders."""
        return Path(settings.MEDIA_ROOT) / "proxy"

    def build_command(self) -> str:
        """Build the ffmpeg command for proxy renders."""
        if not self.output_filename:
            self.output_filename = self.build_out_filename()
        input_dir = Path(self.game.tournament.source_dir)
        out_file = self.full_output_path()
        out_file.parent.mkdir(parents=True, exist_ok=True)

        concat_file = self._build_concat_file(input_dir, self.game.files)
        preset_args = self._preset_args()
        hwaccel = self._hwaccel_args()
        self.command = (
            f"ffmpeg {hwaccel} -y -f concat -safe 0 -i {concat_file} "
            f"{preset_args} {out_file}"
        )
        return self.command

    def _link_storage_symlink(self) -> None:
        """Link proxy output and update game metadata."""
        super()._link_storage_symlink()
        destination = self.media_path() / Path(self.output_filename).name
        proxy_name = str(destination.relative_to(Path(settings.MEDIA_ROOT)))
        if self.game.source_proxy:
            self.game.source_proxy.delete(save=False)
        self.game.source_proxy.name = proxy_name
        self.game.save(update_fields=["source_proxy"])
