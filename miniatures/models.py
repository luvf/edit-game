"""Miniatures models."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.core.files import File
from django.db import models
from django.db.models import F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Length
from django.utils.text import slugify

import game_edit
from game_edit.models import Tournament
from jugger_video_manipulation.build_miniature import Rescale, generate_miniature
from jugger_video_manipulation.utils import get_chapters, get_frame
from miniatures.youtube_interaction.yt_interaction import YTInteraction, YtVideoMetadata

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager
    from PIL.Image import Image


class TeamLogo(models.Model):
    """Model For a team Logo."""

    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=10)
    image = models.ImageField(upload_to="miniatures/logos", default="default.png")

    # file
    def __str__(self) -> str:
        """Str representation."""
        return self.name

    @property
    def path(self) -> Path:
        """Path representation of the image object."""
        return Path(self.image.path)

    @classmethod
    def identify_team(cls, filename: str) -> tuple[TeamLogo, TeamLogo]:
        """Identify the team from the filename.

        Args:
            filename: name of the file
        """
        objects = cls.objects.annotate(fname=Value(filename))
        request = objects.filter(
            Q(fname__icontains=F("short_name")) | Q(fname__icontains=F("name"))
        ).order_by(Length("short_name").asc())
        teams = [TeamLogo.objects.first(), TeamLogo.objects.first(), *request[:2]]
        return teams[-1], teams[-2]


class TmpImage(models.Model):
    """Model For a simple image in database."""

    name = models.CharField(max_length=100)
    date = models.DateField(auto_now_add=True)
    image = models.ImageField(upload_to="tmp", default="default.png")

    def __str__(self) -> str:
        """Str representation."""
        return self.name

    @property
    def path(self) -> Path:
        """Path representation of the image object."""
        return Path(self.image.path)

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,  # noqa: FBT001, FBT002
    ) -> tuple[int, dict[str, int]]:
        """Delete the image."""
        storage = self.image.storage
        # Delete the model before the file
        # Delete the file after the model
        if storage.exists(self.image.name):
            storage.delete(self.image.name)

        return super().delete(using=using, keep_parents=keep_parents)

    def from_pil(self, image: Image) -> None:
        """Get a PIL image and save it in the database."""
        blob = BytesIO()
        image.save(blob, "JPEG")

        self.image.save(self.name, File(blob), save=False)


class VideoMetadataManager(models.Manager["VideoMetadata"]):
    """Manager for video medatada."""

    def create(self, **obj_data: Any) -> VideoMetadata:
        """Create a new VideoMetadata object."""
        tournament = cast(Tournament, obj_data["tournament"])
        team1, team2 = (
            cast(TeamLogo, obj_data["team1"]),
            cast(TeamLogo, obj_data["team2"]),
        )
        name = cast(str, obj_data["name"])
        _ = cast(float, obj_data["time_code"])

        obj_data["description"] = self.description(tournament, name, team1, team2)
        obj_data["video_name"] = (
            f"{name} vs {team1.name} vs {team2.name} | {tournament.name.upper()} [JUGGER]"
        )

        obj_data["publication_date"] = datetime.combine(
            date=datetime.now(tz=UTC).date() - timedelta(days=1), time=time(hour=18)
        )

        # Now call the super method which does the actual creation
        return super().create(**obj_data)

    @staticmethod
    def description(
        tournament: Tournament,
        name: str,
        team1: TeamLogo,
        team2: TeamLogo,
    ) -> str:
        """Generate the description.

        Args:
            tournament: related tournament
            name: video name
            team1: first team logo
            team2: second team logo
        Returns:
            str: video description
        """
        description = [
            team1.name + " vs " + team2.name,
            "Refered by : ",
            str(tournament.date),
            "",
            tournament.tugeny_link,
            tournament.JTR,
            "",
        ]
        timecodes: list[str] = []
        for i, chapter in enumerate(
            get_chapters(tournament.get_rendered_path() / Path(name))
        ):
            timecodes.append(chapter["start"] + " Point " + str(i + 1))
        description += timecodes
        return "\n".join(description)


class VideoMetadata(models.Model):
    """Model for Video Metadata."""

    name = models.CharField(max_length=100)
    tournament = models.ForeignKey(
        game_edit.models.Tournament,
        on_delete=models.SET_NULL,
        null=True,
        related_name="video_metadatas",
    )

    time_code = models.FloatField(default=0)
    miniature_x_offset = models.FloatField(default=0)
    miniature_y_offset = models.FloatField(default=0)
    miniature_zoom = models.FloatField(default=1)
    base_image = models.ForeignKey(
        TmpImage, on_delete=models.SET_NULL, null=True, related_name="base_image"
    )

    miniature_image = models.ForeignKey(
        TmpImage, on_delete=models.SET_NULL, null=True, related_name="miniature"
    )
    team1 = models.ForeignKey(
        TeamLogo, on_delete=models.SET_NULL, null=True, related_name="team1"
    )
    team2 = models.ForeignKey(
        TeamLogo, on_delete=models.SET_NULL, null=True, related_name="team2"
    )

    video_name = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    publication_date = models.DateTimeField(blank=True, default=datetime.now)

    if TYPE_CHECKING:
        YTlink: RelatedManager[YTVideo]

    objects = VideoMetadataManager()

    class Meta:
        """Games ar referenced by name and tournament."""

        unique_together = ("name", "tournament")

    def reset_metadata(self) -> None:
        """Reset all metadata."""
        self.reset_teams()
        self.reset_description()
        self.reset_vid_name()
        self.save()

    def reset_teams(self) -> None:
        """Reset all both team."""
        teams = TeamLogo.identify_team(self.name)
        self.team1 = teams[0]
        self.team2 = teams[1]

    def reset_description(self) -> None:
        """Reset description."""
        if self.tournament is None or self.team1 is None or self.team2 is None:
            raise ValueError("Tournament, team1 and team2 are not set")
        self.description = VideoMetadata.objects.description(
            self.tournament, self.name, self.team1, self.team2
        )

    def reset_vid_name(self) -> None:
        """Reset the video public name name."""
        if self.tournament is None or self.team1 is None or self.team2 is None:
            raise ValueError("Tournament, team1 and team2 are not set")
        self.video_name = f"{self.team1.name} vs {self.team2.name} | {self.tournament.name.upper()} [JUGGER]"

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,  # noqa: FBT001, FBT002
    ) -> tuple[int, dict[str, int]]:
        """Delete the miniature."""
        if self.miniature_image:
            self.miniature_image.delete()
        return super().delete(using=using, keep_parents=keep_parents)

    def __str__(self) -> str:
        """To string representation."""
        return self.name

    def make_metadata(self) -> dict[str, str]:
        """Generate Youtube video meteadata."""
        context = {}
        if self.team1 is None or self.team2 is None:
            raise ValueError("Teams are not set")
        vid_name = self.team1.name + " vs " + self.team2.name

        if self.tournament is not None:
            context["vid_name"] = (
                f"{vid_name} | {self.tournament.name.upper()} [JUGGER]"
            )

        context["description"] = self.description
        context["pub_date"] = self.publication_date.strftime("%Y-%m-%dT%H:%M")

        return context

    def generate_miniature(self) -> None:
        """Generate the miniature image."""
        if self.tournament is None:
            raise ValueError("Tournament is not set")

        base_file_name = "_".join(
            (self.tournament.slug, slugify(self.name[:-4]), str(self.time_code))
        )

        if (
            self.base_image is not None
            and base_file_name + "_base.jpeg" != self.base_image.image.file
        ):
            self.base_image.delete()

        if (
            self.base_image is None
            or base_file_name + "_base.jpeg" != self.base_image.image.file
        ):
            base_image = get_frame(
                self.tournament.get_rendered_path() / self.name, self.time_code
            )
            self.base_image = TmpImage(name=base_file_name + "_base.jpeg")
            self.base_image.from_pil(base_image)
            self.base_image.save()
        else:
            base_image = self.base_image.image

        rescale = Rescale(
            x_offset=self.miniature_x_offset,
            y_offset=self.miniature_y_offset,
            zoom=self.miniature_zoom,
        )

        if self.team1 is None or self.team2 is None:
            raise ValueError("Teams are not set")
        new_miniature_image = generate_miniature(
            base_image=base_image,
            tournament_name=self.tournament.name,
            tournament_color=self.tournament.color,
            team1=self.team1.path,
            team2=self.team2.path,
            rescale=rescale,
        )

        if self.miniature_image is not None:
            self.miniature_image.delete()

        new_image_filename = base_file_name + "_thumbnail.jpeg"

        miniature_object = TmpImage(name=new_image_filename)
        miniature_object.from_pil(new_miniature_image)

        self.miniature_image = miniature_object
        miniature_object.save()
        self.save()


class YTVideoManager(models.Manager["YTVideo"]):
    """Manager for YTVideo."""

    def update_linked_video(self, tournament: Tournament | None = None) -> None:
        """Update the yt video with the having the same name and the most recent one."""
        selected_videos = VideoMetadata.objects.all()
        if tournament:
            selected_videos = selected_videos.filter(tournament=tournament)
        games = selected_videos.filter(
            Q(name__icontains=OuterRef("title"))
            | Q(video_name__icontains=OuterRef("title"))
        )

        self.update(linked_video=Subquery(games.values("pk")[:1]))


class YTVideo(models.Model):
    """Data Linking the real youtube video."""

    title = models.CharField(max_length=150, default="")
    video_id = models.CharField(max_length=50, unique=True)
    linked_video = models.ForeignKey(
        VideoMetadata,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_yt_videos",
    )

    publication_date = models.DateTimeField(default=date.today)
    privacy_status = models.CharField(max_length=150, default="")

    objects = YTVideoManager()

    def __str__(self) -> str:
        """To string representation."""
        return self.title

    def update(self, data: dict[str, str]) -> None:
        """Update locally the video metadata."""
        self.title = data["title"]
        self.video_id = data["videoid"]
        if self.linked_video is not None:
            self.linked_video.description = data["description"]
        self.publication_date = data["date"]
        self.privacy_status = data["privacystatus"]

    def upload_description(self) -> None:
        """Met à jour le titre/description/statut de la vidéo YouTube liée."""
        if not self.linked_video:
            return
        yt_interaction = YTInteraction()
        response = yt_interaction.update_video(YtVideoMetadata.from_ytvideo_model(self))
        # MàJ des champs locaux
        self.title = response.title
        self.privacy_status = response.status
        self.publication_date = response.date
        self.save()

    def upload_miniature(self) -> None:
        """Met à jour uniquement la miniature (thumbnail) de la vidéo YouTube liée."""
        if self.linked_video is None or self.linked_video.miniature_image is None:
            return
        YTInteraction().set_miniature(
            self.video_id, self.linked_video.miniature_image.path
        )
        # Pas de champs locaux à mettre à jour ici, on persiste l'état actuel
        self.save()

    @classmethod
    def youtube_update(
        cls, tournament: Tournament, *, sync_local_videos: bool = False
    ) -> None:
        """Update all the videos from the tournament.

        Args:
            tournament: Tournament object where the videos are uploaded.
            sync_local_videos: if True, update the local videos with the ones on youtube
        """
        yt_interaction = YTInteraction()
        videos = yt_interaction.get_all_videos()
        for video in videos:
            vid, _ = YTVideo.objects.get_or_create(
                video_id=video.video_id,
                defaults={
                    "title": video.title,
                    "publication_date": video.date,
                    "privacy_status": video.status,
                },
            )

            if vid.title != video.title:
                vid.title = video.title
                vid.publication_date = video.date
                vid.privacy_status = video.status

            if sync_local_videos:
                filtered_videos_metadata = VideoMetadata.objects.filter(
                    (Q(name=vid.title) & Q(tournament=tournament))
                    | Q(video_name=vid.title)
                )

                if vid.linked_video is None and filtered_videos_metadata.exists():
                    vid.linked_video = filtered_videos_metadata[0]
            vid.save()
