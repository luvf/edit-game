"""Admin config for miniatures app."""

from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib import admin

from miniatures.models import TeamLogo, TmpImage, VideoMetadata, YTVideo

admin.site.register(TeamLogo)

if TYPE_CHECKING:
    VidMetadataAdminBase = admin.ModelAdmin[VideoMetadata]
    TmpImageAdminBase = admin.ModelAdmin[TmpImage]
    YTVideoAdminBase = admin.ModelAdmin[YTVideo]
else:
    VidMetadataAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    TmpImageAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    YTVideoAdminBase = admin.ModelAdmin  # type: ignore[assignment]


@admin.register(VideoMetadata)
class VidMetadataAdmin(VidMetadataAdminBase):
    """Admin config for VidMetadata."""

    list_display = (
        "name",
        "tournament",
        "team1",
        "team2",
        "publication_date",
        "tc",
    )
    fields = (
        "name",
        "tournament",
        ("team1", "team2"),
        ("miniature_image", "tc"),
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
