"""Cut generation queue item: runs `prepare_segments` to fill a Cut JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import models

from core.models.render_queue.base import RenderQueueItemBase
from jugger_video_manipulation.cut_from_rendered import prepare_segments
from jugger_video_manipulation.ffmpeg_utils import get_chapters


class RenderQueueItemGenCut(RenderQueueItemBase):
    """Queue item that generates a Cut's JSON from a rendered video."""

    cut = models.ForeignKey("core.Cut", on_delete=models.CASCADE)
    rendered_path = models.CharField(max_length=512)
    tmp_dir = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        """Model metadata."""

        db_table = "game_edit_render_queue_gen_cut"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the job type matches gen-cut jobs."""
        self.job_type = self.JobType.GEN_CUT
        super().save(*args, **kwargs)

    def _execute(self) -> None:
        """Run prepare_segments and persist the result on the cut."""
        game = self.cut.game
        if not game or not isinstance(game.files, list) or not game.files:
            self.cut.set_json({"points": [], "overlays": []})
            return

        source_dir = game.tournament.media_path
        tmp_path = (
            Path(self.tmp_dir) if self.tmp_dir else Path(settings.BASE_DIR) / "tmp"
        )
        if not get_chapters(video_file=Path(self.rendered_path)):
            self.error = "No chapters found in edited file."
            self.save()
            return
        points = prepare_segments(
            rush_files=[source_dir / "rushs" / f for f in game.files],
            edited_file=Path(self.rendered_path),
            tmp_dir_path=tmp_path,
        )
        self.cut.set_json({"points": points, "overlays": []})

    @property
    def metadata(self) -> str:
        """Return metadata for this queue item, if any."""
        return f"{Path(self.rendered_path).name}"

    @property
    def command_parameters(self) -> str:
        """Return command parameters for the render queue item."""
        game = self.cut.game
        return (
            f"rush dir :{game.tournament.media_path / 'rushs' }  "
            f"rush_files :{game.files}  "
            f"edited_file:{Path(self.rendered_path).name}  "
            f"tmp_dir_path :{Path(self.tmp_dir) if self.tmp_dir else Path(settings.BASE_DIR) / "tmp"}"
        )
