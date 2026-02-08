"""Tournament and team models."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, cast

from colorfield.fields import ColorField
from django.apps import apps
from django.conf import settings
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Length
from django.utils.text import slugify

from core.models.game import Game
from core.utils.dataset_utils import get_base_json


class Tournament(models.Model):
    """Tournament model."""

    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=14)
    date = models.DateField()
    place = models.CharField(max_length=200, default="")
    JTR = models.CharField(max_length=200, default="", blank=True)
    tugeny_link = models.CharField(max_length=200, default="", blank=True)
    color = ColorField(default="#0000")
    drive_dir = models.CharField(
        max_length=200, default=str(settings.TOURNAMENTS_BASE_DIR)
    )
    tournament_dir = models.CharField(max_length=200, default="", blank=True)
    slug = models.SlugField(default="", null=False)

    class Meta:
        """Model metadata."""

        db_table = "game_edit_tournament"

    @property
    def source_dir(self) -> str:
        """Get the source directory from drive and tournament directories."""
        drive = self.drive_dir or ""
        if self.tournament_dir:
            return str(Path(drive) / self.tournament_dir)
        if drive:
            return str(Path(drive))
        return str(Path(self.tournament_dir))

    @property
    def source_dir_path(self) -> Path:
        """Get the path to the source directory."""
        return Path(self.source_dir)

    def __str__(self) -> str:
        """To string representation."""
        return self.name

    def get_rendered_path(self, subdir: Path = Path("rendered")) -> Path:
        """Get the path to the rendered directory."""
        return self.source_dir_path / subdir

    def get_timelines_path(self, subdir: Path = Path("timelines")) -> Path:
        """Get the path to the timelines directory."""
        return self.source_dir_path / subdir

    def generate_games(self) -> list[Game]:
        """Generate games from the source dir."""
        game_model = apps.get_model("core", "Game")
        vid_dir = self.source_dir_path / "rushs"
        exp = re.compile(r"^GX(\d{2})(\d{4})\.MP4$")
        videos = defaultdict(list)
        created_gamse = []

        for path in vid_dir.iterdir():
            if (vid_dir / path).is_file() and path.suffix == ".MP4":
                val = exp.search(str(path.name))
                if val is None:
                    continue
                videos[int(val.group(2))].append(int(val.group(1)))
        for key, video_id in videos.items():
            base_name = "VID00" + str(key) + ".json"
            video_id.sort()
            filenames = [
                "GX" + str(vId).zfill(2) + str(key).zfill(4) + ".MP4"
                for vId in video_id
            ]
            if len(game_model.objects.filter(files=filenames)) == 0:
                data = json.loads(get_base_json())
                data["dir"] = self.source_dir
                data["files"] = filenames
                data["filename"] = base_name
                file = StringIO(json.dumps(data, indent=4))

                game = game_model(
                    name=str(key),
                    files=filenames,
                    slug=slugify(base_name),
                    tournament=self,
                    rendered="",
                )

                filename = self.name + "_" + str(key) + "_game.json"
                game.json_file.save(filename, file)

                game.save()
                created_gamse.append(game)
        return cast(list[Game], created_gamse)


class Team(models.Model):
    """Model for a team."""

    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=10)
    slug = models.SlugField(default="", blank=True)
    image = models.ImageField(upload_to="miniatures/logos", default="default.png")

    class Meta:
        """Model metadata."""

        db_table = "miniatures_team"

    def __str__(self) -> str:
        """Str representation."""
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Auto-populate slug from name if missing."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def path(self) -> Path:
        """Path representation of the image object."""
        return Path(self.image.path)

    @classmethod
    def identify_team(cls, filename: str) -> tuple[Team, Team]:
        """Identify the team from the filename."""
        objects = cls.objects.annotate(fname=Value(filename))
        request = objects.filter(
            Q(fname__icontains=F("short_name")) | Q(fname__icontains=F("name"))
        ).order_by(Length("short_name").asc())
        teams = [Team.objects.first(), Team.objects.first(), *request[:2]]
        return teams[-1], teams[-2]
