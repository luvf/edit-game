"""Game model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from django.db import models


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
    ) -> "RenderQueueItem":
        """Create a proxy render queue item handled by RenderQueueItemProxy.

        Behavior:
        - Always creates a queue item; rendering happens in the worker.
        - The queue item handles file generation and linking during execution.

        Raises:
        - ValueError if the preset is invalid or if no source files are available.
        """
        if preset not in ["low", "medium", "high"]:
            raise ValueError("Preset must be low, medium or high")

        from core.models.render_queue import RenderQueueItem, RenderQueueItemProxy

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
