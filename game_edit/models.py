"""Django Models edit_game, contains Tournament, Team, Game and Cut models."""

import json
import re
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, ClassVar, cast

from colorfield.fields import ColorField
from django.db import models
from django.utils.text import slugify

# Create your models here.
from game_edit.utils.dataset_utils import get_base_json
from jugger_video_manipulation.cut_from_rendered import use_scipy


class Tournament(models.Model):
    """Tournament model.

    contains fields:
        name: name of the tournament
        short_name: short name of the tournament
        date: date of the tournament should be the first day of the tournament
        JTR: jugger turiniere url
        tugeny_link: link to the tugeny website
        color: background color of the overlay
        source_dir: path to the source directory for videos
            (this dir must contain rushs, and rendered, subdirs)
        slug: slug of the tournament

    """

    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=14)
    date = models.DateField()
    place = models.CharField(max_length=200, default="")
    JTR = models.CharField(max_length=200, default="", blank=True)
    tugeny_link = models.CharField(max_length=200, default="", blank=True)
    color = ColorField(default="#0000")

    source_dir = models.CharField(max_length=200, default="-")
    slug = models.SlugField(default="", null=False)

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

    def generate_games(self) -> None:
        """Generate games from the source dir."""
        vid_dir = self.source_dir_path / "rushs"
        exp = re.compile(r"^GX(\d{2})(\d{4})\.MP4$")
        videos = defaultdict(list)
        for path in vid_dir.iterdir():
            if (vid_dir / path).is_file() and path.suffix == ".MP4":
                val = exp.search(str(path))
                if val is None:
                    continue
                videos[int(val.group(2))].append(int(val.group(1)))

        for key, video_id in videos.items():
            base_name = "VID00" + str(key) + ".json"
            if len(Game.objects.filter(source_name=base_name)) == 0:
                video_id.sort()
                filenames = [
                    "GH" + str(vId).zfill(2) + str(key).zfill(4) + ".MP4"
                    for vId in video_id
                ]

                data = json.loads(get_base_json())
                data["dir"] = self.source_dir
                data["files"] = filenames
                data["filename"] = base_name
                file = StringIO(json.dumps(data, indent=4))

                game = Game(
                    name=str(key),
                    source_name=str(key),
                    slug=slugify(base_name),
                    tournament=self,
                    rendered="",
                )  # json_file=blob)

                filename = self.name + "_" + str(key) + "_game.json"
                game.json_file.save(filename, file)

                game.save()


class Team(models.Model):
    """model for teams.

    contains fields:
        name: name of the team.
        logo: logo of the team, links the TeamLogo model.
        slug: slug of the team.
    """

    name = models.CharField(max_length=100)
    logo = models.ForeignKey(
        "miniatures.TeamLogo",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="teams",
    )
    slug = models.SlugField(default="", null=False)

    def __str__(self) -> str:
        """To string representation."""
        return self.name


class Game(models.Model):
    """Game model."""

    name = models.CharField(max_length=100)

    source_name = models.CharField(max_length=100)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    team1 = models.ForeignKey(
        Team, on_delete=models.SET_NULL, related_name="Team1", null=True
    )
    team2 = models.ForeignKey(
        Team, on_delete=models.SET_NULL, related_name="Team2", null=True
    )
    # points

    rendered = models.CharField(max_length=200, blank=True)
    json_file = models.FileField(upload_to="json_files", default="tt")

    source_proxy = models.FileField(upload_to="game_edit/previews", default="")

    slug = models.SlugField(default="", null=False)

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

    def render_cuts(self, directory: Path) -> dict[str, Any]:
        """Render cuts from json file."""
        target_file = directory / "rendered" / self.rendered
        return use_scipy(
            self.get_json(),
            target_file,
            tmp_dir="game_edit/tmp",
            build_tmp=True,
            sample_rate=16000,
        )


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
    json_file = models.FileField(upload_to="json_files", default="tt")
    slug = models.SlugField(default="", null=False)
    game = models.ForeignKey(Game, on_delete=models.SET_NULL, null=True)

    def __str__(self) -> str:
        """To string representation."""
        return self.name
