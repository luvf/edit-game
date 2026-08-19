"""Admin config for core app."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib import admin

from core.models.cut import Cut
from core.models.game import Game
from core.models.media import TmpImage, VideoMetadata, YTVideo
from core.models.render_queue.ffmpeg import (
    RenderQueueItemArchive,
    RenderQueueItemCut,
    RenderQueueItemProxy,
)
from core.models.render_queue.gen_cut import RenderQueueItemGenCut
from core.models.tournament import Team, Tournament
from core.models.video import Video, VideoFile

type ListDisplay = list[Any] | tuple[Any, ...]

if TYPE_CHECKING:
    TournamentAdminBase = admin.ModelAdmin[Tournament]
    GameAdminBase = admin.ModelAdmin[Game]
    TeamAdminBase = admin.ModelAdmin[Team]
    VidMetadataAdminBase = admin.ModelAdmin[VideoMetadata]
    TmpImageAdminBase = admin.ModelAdmin[TmpImage]
    YTVideoAdminBase = admin.ModelAdmin[YTVideo]
    CutAdminBase = admin.ModelAdmin[Cut]
    VideoAdminBase = admin.ModelAdmin[Video]
    VideoFileAdminBase = admin.ModelAdmin[VideoFile]
else:
    TournamentAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    GameAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    TeamAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    VidMetadataAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    TmpImageAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    YTVideoAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    CutAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    VideoAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    VideoFileAdminBase = admin.ModelAdmin  # type: ignore[assignment]


@admin.register(Tournament)
class TournamentAdmin(TournamentAdminBase):
    """Tournament admin panel."""

    list_display: ClassVar[ListDisplay] = (  # type: ignore[misc]
        "name",
        "short_name",
        "place",
        "date",
        "JTR",
        "tugeny_link",
    )
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ["name"]}


@admin.register(Game)
class GameAdmin(GameAdminBase):
    """Game admin panel."""

    list_display: ClassVar[ListDisplay] = (  # type: ignore[misc]
        "name",
        "tournament",
        "team1",
        "team2",
        "json_file",
        "video_proxy",
        "archive_video",
    )
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ["name"]}
    autocomplete_fields = ("archive_video",)


@admin.register(Team)
class TeamAdmin(TeamAdminBase):
    """Team admin panel."""

    list_display: ClassVar[ListDisplay] = ("name", "short_name", "slug")  # type: ignore[misc]


@admin.register(VideoMetadata)
class VidMetadataAdmin(VidMetadataAdminBase):
    """Admin config for VideoMetadata."""

    list_display = (
        "name",
        "tournament",
        "team1",
        "team2",
        "publication_date",
        "time_code",
    )
    fields = (
        "name",
        "tournament",
        ("team1", "team2"),
        ("miniature_image", "time_code"),
        ("video_name", "publication_date", "description"),
    )
    list_filter: ClassVar[list[Any]] = [
        "tournament",
    ]


@admin.register(TmpImage)
class TmpImageAdmin(TmpImageAdminBase):
    """Admin config for TmpImage."""

    list_display = ("name", "image")


@admin.register(YTVideo)
class YTVideoAdmin(YTVideoAdminBase):
    """Admin config for YTVideo."""

    list_display = ("title", "video_id", "publication_date")
    ordering = ("-publication_date",)


@admin.register(Cut)
class CutAdmin(CutAdminBase):
    """Admin config for Cut."""

    list_display = ("name", "game", "slug", "rendered_video")


@admin.register(Video)
class VideoAdmin(VideoAdminBase):
    """Admin config for Video."""

    list_display = ("name", "status", "games", "cuts")
    list_filter = ("status",)
    search_fields = ("name",)

    fields = ("name", "status", "uuid")
    readonly_fields = ("uuid",)

    def games(self, obj: Video) -> Game | None:
        """Get the game associated with this video, if any."""
        if hasattr(obj, "game"):
            return obj.game
        return None

    def cuts(self, obj: Video) -> Cut | None:
        """Get the cut associated with this video, if any."""
        if hasattr(obj, "cut"):
            return obj.cut

        return None


@admin.register(VideoFile)
class VideoFileAdmin(VideoFileAdminBase):
    """Admin config for VideoFile."""

    list_display = (
        "video__name",
        "path",
        "quality",
    )
    search_fields = ("video__name",)
    fields = ("video", "path", "quality")


admin.site.register(RenderQueueItemCut)
admin.site.register(RenderQueueItemProxy)
admin.site.register(RenderQueueItemArchive)
admin.site.register(RenderQueueItemGenCut)
