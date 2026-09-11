"""ML cut queue item: runs the trained model and attaches what it proposed."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models

from core.models.render_queue.base import RenderQueueItemBase


class RenderQueueItemMlCut(RenderQueueItemBase):
    """Queue item that fills a Cut from the auto-edit model.

    The model runs in a subprocess rather than in the worker: loading a
    checkpoint pulls torch in and holds VRAM for the life of the process,
    while the worker is meant to outlive every job it runs. The queue's single
    running job is what keeps the model and an nvenc render off the same card
    at the same time.
    """

    cut = models.ForeignKey("core.Cut", on_delete=models.CASCADE)
    run_name = models.CharField(max_length=100, blank=True, default="")
    threshold_in = models.FloatField(default=0.50)
    threshold_out = models.FloatField(default=0.70)
    min_gap = models.FloatField(default=30.0)
    snap = models.BooleanField(default=True)
    report = models.TextField(blank=True, default="")

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_ml_cut"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches ML cut generation."""
        self.job_type = self.JobType.ML_CUT
        super().save(*args, **kwargs)

    @property
    def effective_run(self) -> str:
        """Return the run this job uses, falling back to the configured one."""
        return self.run_name or str(settings.AUTOEDIT_RUN)

    def build_command(self, out_dir: Path) -> list[str]:
        """Build the command line that proposes the cut.

        `sys.executable` rather than a bare `python`: the worker runs inside
        the project's virtualenv and the subprocess must land in the same one.
        """
        command = [
            sys.executable,
            "-m",
            "game_autoedit",
            "propose",
            "--game",
            str(self.cut.game_id),
            "--cut",
            str(self.cut_id),
            "--run",
            self.effective_run,
            "--out",
            str(out_dir),
            "--threshold-in",
            str(self.threshold_in),
            "--threshold-out",
            str(self.threshold_out),
            "--min-gap",
            str(self.min_gap),
        ]
        command.append("--snap" if self.snap else "--no-snap")
        return command

    def _execute(self) -> None:
        """Run the model, then attach its cut file and its curves."""
        tmp_root = Path(settings.BASE_DIR) / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        out_dir = Path(tempfile.mkdtemp(prefix="ml_cut_", dir=tmp_root))
        try:
            self._run_subprocess(self.build_command(out_dir))
            self._attach(out_dir)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def _attach(self, out_dir: Path) -> None:
        """Move the proposal from the working directory onto the cut.

        Raises:
            RuntimeError: the subprocess reported success but wrote nothing.
        """
        game_id = self.cut.game_id
        cut_path = out_dir / f"game_{game_id}_cut.json"
        curves_path = out_dir / f"game_{game_id}_curves.npz"
        if not cut_path.exists():
            raise RuntimeError(f"aucun cut produit dans {out_dir}")

        payload = json.loads(cut_path.read_text())
        self.cut.set_json(payload)

        if curves_path.exists():
            self.cut.curves_file.save(
                f"cut_{self.cut_id}_curves_{uuid.uuid4().hex[:8]}.npz",
                ContentFile(curves_path.read_bytes()),
                save=True,
            )

        comment = payload.get("comment", {})
        stats = comment.get("stats", {})
        self.report = (
            f"{len(payload.get('points', []))} segments, "
            f"{stats.get('kept', 0) / 60:.1f} min gardées, "
            f"{len(comment.get('review', []))} point(s) à vérifier"
        )
        self.save(update_fields=["report"])

    @property
    def metadata(self) -> str:
        """Return metadata for this queue item, if any."""
        return self.report or self.effective_run

    @property
    def command_parameters(self) -> str:
        """Return command parameters for the render queue item."""
        return " ".join(self.build_command(Path(settings.BASE_DIR) / "tmp"))
