"""Cut model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar, cast

import opentimelineio as otio
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.db.models import OneToOneField

from core.models.render_queue.ffmpeg import RenderQueueItemCut
from core.models.render_queue.gen_cut import RenderQueueItemGenCut
from core.models.video import Video


class Cut(models.Model):
    """Cut model, represents a cut directives to edit the video."""

    CUT_TYPES: ClassVar[list[tuple[str, str]]] = [
        ("MAN", "manual"),
        ("VID", "from video"),
        ("XML", "from XML"),
        ("OTIO", "from OTIO json file"),
        ("ML", "from ML"),
        ("X", "others"),
    ]
    name = models.CharField(max_length=100)
    type_cut = models.CharField(max_length=50, choices=CUT_TYPES)
    json_file = models.FileField(
        upload_to="json_files/cuts/", default="json_files/cuts/default.json"
    )
    slug = models.SlugField(default="", null=False)
    game = models.ForeignKey("core.Game", on_delete=models.CASCADE, related_name="cuts")
    rendered_video = OneToOneField(
        Video, on_delete=models.SET_NULL, null=True, blank=True, related_name="cut"
    )

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

    def set_json(self, json_data: dict[str, Any]) -> None:
        """Persist JSON payload into the cut file."""
        filename = f"cut_{self.pk}_data.json"
        content = ContentFile(json.dumps(json_data, ensure_ascii=False).encode("utf-8"))
        self.json_file.save(filename, content, save=True)

    def ensure_video(self) -> None:
        """Create and attach a video if missing."""
        if self.rendered_video:
            return

        from core.models.video import Video

        self.rendered_video = Video.objects.create(name=self.name)
        self.save(update_fields=["rendered_video"])

    def gen_from_file(self, file_content: bytes | str) -> dict[str, Any]:
        """Generate cut json payload from a file content."""
        if isinstance(file_content, str):
            file_content = file_content.encode("utf-8")
        if self.type_cut == "OTIO" and True:
            return self.gen_from_otio(file_content)
        return {}

    @staticmethod
    def gen_from_otio(file_content: bytes) -> dict[str, Any]:
        """Assumes the in files are countious.

        :param
            file_content: the otio json file content.
        :return:
            the json with points and overlays.
        """
        otio_file = otio.adapters.otio_json.read_from_string(
            file_content.decode("utf-8")
        )  # type: ignore[no-untyped-call]
        main_track = otio_file.tracks[0]
        first_clip_start_time = main_track[0].available_range().start_time.value
        points = []
        for clip in main_track:
            if clip.schema_name() != "Clip":
                continue
            duration = clip.source_range.duration.value
            start_time = clip.source_range.start_time.value
            in_tc = start_time - first_clip_start_time
            out_tc = in_tc + duration
            points.append({"in": in_tc, "out": out_tc})
        trim_points: list[dict[str, float]] = []
        for i, point in enumerate(points):
            if i > 0 and abs(point["in"] - points[i - 1]["out"]) <= 1:
                trim_points[-1]["out"] = point["out"]
            else:
                trim_points.append(point)

        return {"points": trim_points, "overlays": []}

    def gen_from_rendered_queue(
        self,
        rendered_path: str | Path,
        *,
        tmp_dir: str | Path | None = None,
    ) -> RenderQueueItemGenCut:
        """Generate a RenderQueueItemGenCut for this cut from a rendered video file."""
        tmp_path = Path(tmp_dir) if tmp_dir else Path(settings.BASE_DIR) / "tmp"

        return RenderQueueItemGenCut.objects.create(
            cut=self,
            rendered_path=f"{rendered_path}",
            tmp_dir=f"{tmp_path}",
        )

    def render_to_queue(
        self, *, preset: str = "medium", run_now: bool = False
    ) -> RenderQueueItemCut:
        """Create a queue item for this cut render."""
        self.ensure_video()

        render_queue_item = RenderQueueItemCut.objects.create(
            cut=self,
            preset=preset,
        )
        if run_now:
            render_queue_item.run()
        return render_queue_item
