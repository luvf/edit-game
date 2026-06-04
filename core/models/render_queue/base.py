"""Base render queue item: lifecycle management shared by all job types."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Q

if TYPE_CHECKING:
    from core.models.cut import Cut
    from core.models.game import Game


class RenderQueueItemBase(models.Model):
    """Concrete base for all render queue items (multi-table inheritance root)."""

    class JobType(models.TextChoices):
        """Job types for queue items."""

        CUT_RENDER = "CUT_RENDER", "cut_render"
        GAME_PROXY = "GAME_PROXY", "game_proxy"
        GEN_CUT = "GEN_CUT", "gen_cut"

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
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CREATED
    )
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
            label = self.game.name if self.game else "unknown game"
        elif self.job_type in (self.JobType.CUT_RENDER, self.JobType.GEN_CUT):
            label = self.cut.name if self.cut else "unknown cut"
        else:
            label = f"job {self.pk}"
        return f"{label} [{self.status}]"

    @property
    def cut(self) -> Cut | None:
        """Return the associated cut, if any."""
        try:
            return self.renderqueueitemffmpeg.renderqueueitemcut.cut
        except ObjectDoesNotExist:
            pass
        try:
            return self.renderqueueitemgencut.cut
        except ObjectDoesNotExist:
            return None

    @property
    def game(self) -> Game | None:
        """Return the associated game, if any."""
        if self.cut:
            try:
                return self.cut.game
            except ObjectDoesNotExist:
                return None
        try:
            return self.renderqueueitemffmpeg.renderqueueitemproxy.game
        except ObjectDoesNotExist:
            return None

    def concrete(self) -> RenderQueueItemBase:
        """Return the concrete queue item instance for this row."""
        from core.models.render_queue.ffmpeg import (
            RenderQueueItemCut,
            RenderQueueItemProxy,
        )
        from core.models.render_queue.gen_cut import RenderQueueItemGenCut

        if self.job_type == self.JobType.CUT_RENDER:
            return RenderQueueItemCut.objects.get(pk=self.pk)
        if self.job_type == self.JobType.GAME_PROXY:
            return RenderQueueItemProxy.objects.get(pk=self.pk)
        if self.job_type == self.JobType.GEN_CUT:
            return RenderQueueItemGenCut.objects.get(pk=self.pk)
        raise ValueError(f"Unsupported job type: {self.job_type}")

    def run(self) -> None:
        """Execute this queue item; subclasses override `_execute`."""
        self._execute()

    def _execute(self) -> None:
        """Concrete subclasses must implement the actual work."""
        raise NotImplementedError("Use a concrete queue item type.")

    def _run_subprocess(self, command: list[str]) -> None:
        """Run a subprocess command while tracking its pid on the row."""
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
                raise RuntimeError(f"command failed (code {returncode}): {details}")
            raise RuntimeError(f"command failed with code {returncode}.")

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
            RenderQueueItemBase.objects.filter(status=self.Status.RUNNING)
            .exclude(pk=self.pk)
            .exists()
        )

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,  # noqa: FBT001, FBT002
    ) -> tuple[int, dict[str, int]]:
        """Default delete; ffmpeg subclass overrides to clean tmp files."""
        return super().delete(using=using, keep_parents=keep_parents)
