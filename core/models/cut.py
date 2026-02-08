"""Cut model."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models

from jugger_video_manipulation.cut_from_rendered import (
    build_cut_points_from_rendered_audio,
)
from jugger_video_manipulation.cut_from_rendered_frames import (
    build_cut_points_from_rendered_frames,
)

if TYPE_CHECKING:
    from core.models.render_queue import RenderQueueItemCut


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
    game = models.ForeignKey("core.Game", on_delete=models.SET_NULL, null=True)

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

    def gen_from_xml(self, xml_content: bytes | str) -> dict[str, Any]:
        """Generate cut json payload from a DaVinci Resolve XML."""
        if isinstance(xml_content, str):
            xml_payload = xml_content.encode("utf-8")
        else:
            xml_payload = xml_content

        if not self.game or not isinstance(self.game.files, list):
            return {"points": [], "overlays": []}

        def normalize_filename(value: str) -> str:
            return Path(value).name.strip().lower()

        game_files = {normalize_filename(name) for name in self.game.files}
        if not game_files:
            return {"points": [], "overlays": []}

        # TODO: Confirm DaVinci XML timing fields vs concatenated game file offsets.
        root = ET.fromstring(xml_payload)
        points: list[dict[str, int | str]] = []
        for clip in root.findall(".//video//clipitem"):
            file_name = clip.findtext("file/name") or clip.findtext("name") or ""
            if not file_name:
                continue
            if normalize_filename(file_name) not in game_files:
                continue

            def to_int(value: str | None) -> int | None:
                if value is None:
                    return None
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            start_frame = to_int(clip.findtext("start"))
            end_frame = to_int(clip.findtext("end"))
            if start_frame is None or end_frame is None:
                start_frame = to_int(clip.findtext("in"))
                end_frame = to_int(clip.findtext("out"))
            if start_frame is None or end_frame is None:
                continue
            if end_frame < start_frame:
                continue

            points.append({"in": start_frame, "out": end_frame, "point": "nopoint"})

        points.sort(key=lambda item: cast(int, item["in"]))
        return {"points": points, "overlays": []}

    def gen_from_rendered(
        self,
        rendered_path: str | Path,
        *,
        sample_rate: int = 16000,
        use_frames: bool = True,
        tmp_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Generate cut json payload from a rendered video file."""
        if not self.game or not isinstance(self.game.files, list):
            return {"points": [], "overlays": []}
        if not self.game.files:
            return {"points": [], "overlays": []}

        source_dir = Path(self.game.tournament.source_dir)
        tmp_path = Path(tmp_dir) if tmp_dir else Path(settings.BASE_DIR) / "tmp"
        if use_frames:
            proxy_path = None
            if self.game.source_proxy and self.game.source_proxy.name:
                candidate = self.game.source_proxy_path
                if candidate.exists():
                    proxy_path = candidate
            if proxy_path is None:
                self.game.generate_proxy(preset="medium")
                self.game.refresh_from_db(fields=["source_proxy"])
                if self.game.source_proxy and self.game.source_proxy.name:
                    candidate = self.game.source_proxy_path
                    if candidate.exists():
                        proxy_path = candidate
            if proxy_path is None:
                raise FileNotFoundError("Proxy generation failed for frame matching.")
            points = build_cut_points_from_rendered_frames(
                source_dir=source_dir,
                source_files=self.game.files,
                target_path=Path(rendered_path),
                source_proxy_path=proxy_path,
                tmp_dir=tmp_path,
            )
        else:
            points = build_cut_points_from_rendered_audio(
                source_dir=source_dir,
                source_files=self.game.files,
                target_path=Path(rendered_path),
                sample_rate=sample_rate,
                tmp_dir=tmp_path,
            )
        return {"points": points, "overlays": []}

    def render(self, *, preset: str = "medium") -> RenderQueueItemCut:
        """Create a queue item for this cut render."""
        item = self.to_queue(preset=preset)
        item.run()
        return item

    def to_queue(self, *, preset: str = "medium") -> RenderQueueItemCut:
        """Create a queue item for this cut render."""
        from core.models.render_queue import RenderQueueItemCut

        return RenderQueueItemCut.objects.create(
            cut=self,
            preset=preset,
        )
