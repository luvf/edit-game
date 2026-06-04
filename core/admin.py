"""Admin config for core app."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib import admin

from core.models import (
    Cut,
    Game,
    RenderQueueItemCut,
    RenderQueueItemGenCut,
    RenderQueueItemProxy,
    Team,
    TmpImage,
    Tournament,
    VideoMetadata,
    YTVideo,
)

type ListDisplay = list[Any] | tuple[Any, ...]

if TYPE_CHECKING:
    TournamentAdminBase = admin.ModelAdmin[Tournament]
    GameAdminBase = admin.ModelAdmin[Game]
    TeamAdminBase = admin.ModelAdmin[Team]
    VidMetadataAdminBase = admin.ModelAdmin[VideoMetadata]
    TmpImageAdminBase = admin.ModelAdmin[TmpImage]
    YTVideoAdminBase = admin.ModelAdmin[YTVideo]
    CutAdminBase = admin.ModelAdmin[Cut]
else:
    TournamentAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    GameAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    TeamAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    VidMetadataAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    TmpImageAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    YTVideoAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    CutAdminBase = admin.ModelAdmin  # type: ignore[assignment]


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
        "rendered",
        "json_file",
    )
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ["name"]}


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


admin.site.register(RenderQueueItemCut)
admin.site.register(RenderQueueItemProxy)
admin.site.register(RenderQueueItemGenCut)
