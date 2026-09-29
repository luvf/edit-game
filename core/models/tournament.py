"""Tournament and team models."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
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
    def media_path(self) -> Path:
        """Get the path to the source directory."""
        drive = self.drive_dir or ""
        return Path(drive) / self.tournament_dir

    @property
    def tournament_media_url(self) -> str:
        """Get the URL to the source directory."""
        if Path(self.drive_dir) == settings.TOURNAMENTS_ARCHIVE_DIR:
            root_url = "http://192.168.1.2:8001/tournois"
        else:
            root_url = "http://127.0.0.1:8081/tournois"

        return f"{root_url}/{self.tournament_dir}"

    def __str__(self) -> str:
        """To string representation."""
        return self.name

    def get_rendered_path(self, subdir: Path = Path("rendered")) -> Path:
        """Get the path to the rendered directory."""
        return self.media_path / subdir

    def generate_games(self) -> list[Game]:
        """Generate games from the source dir."""
        game_model = apps.get_model("core", "Game")
        vid_dir = self.media_path / "rushs"
        exp = re.compile(r"^G[XH](\d{2})(\d{4})\.MP4$")
        videos: defaultdict[int, list[tuple[int, str]]] = defaultdict(list)
        created_gamse = []

        for path in vid_dir.iterdir():
            if (vid_dir / path).is_file() and path.suffix == ".MP4":
                val = exp.search(str(path.name))
                if val is None:
                    continue
                videos[int(val.group(2))].append((int(val.group(1)), path.name))
        for key, video_id in videos.items():
            base_name = "VID00" + str(key) + ".json"
            video_id.sort(key=lambda x: x[0])
            filenames = [video_name for _, video_name in video_id]
            if len(game_model.objects.filter(files=filenames)) == 0:
                data = json.loads(get_base_json())
                data["dir"] = str(self.media_path)
                data["files"] = filenames
                data["filename"] = base_name
                file = StringIO(json.dumps(data, indent=4))

                game = game_model(
                    name=str(key),
                    files=filenames,
                    slug=slugify(base_name),
                    tournament=self,
                )

                filename = self.name + "_" + str(key) + "_game.json"
                game.json_file.save(filename, file)

                game.save()
                created_gamse.append(game)
        return cast(list[Game], created_gamse)

    def archive(self) -> None:
        """Archive the tournament by moving files to the archive directory."""
        archive_dir = settings.TOURNAMENTS_ARCHIVE_DIR
        self.drive_dir = str(archive_dir)

        self.save(update_fields=["drive_dir"])

    def refresh_video_files(self) -> Counter[str]:
        """Re-check every video file of this tournament, and repair what can be.

        Changing `drive_dir` moves `media_path`, but a VideoFile stores an
        absolute path taken at render time: after an archive the rows still
        point at the old drive. Each row is relocated to the directory the
        tournament now resolves to, and its fps refreshed along the way.

        Returns how many rows landed in each VideoFile.FileCheck outcome.
        """
        video_file_model = apps.get_model("core", "VideoFile")
        outcomes: Counter[str] = Counter()
        for video_file in video_file_model.objects.for_tournament(self):
            outcome, _ = video_file.check_file()
            outcomes[outcome] += 1
        return outcomes


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
