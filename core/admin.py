"""Admin config for core app."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.views.main import ORDER_VAR
from django.db.models import BooleanField, Case, Value, When
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join

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
from core.utils import orphan_videos

type ListDisplay = list[Any] | tuple[Any, ...]

# A run over the whole table can find hundreds of broken files; listing them
# all would bury the summary under a wall of admin messages.
MAX_REPORTED_BROKEN_FILES = 20

# Name of the annotation carrying the disk state, so the column can be sorted.
ON_DISK_ANNOTATION = "file_present"

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse
    from django.utils.safestring import SafeString

    from core.models.video import VideoFileQuerySet, VideoQuerySet
    from core.utils.orphan_videos import OrphanReport

    TournamentAdminBase = admin.ModelAdmin[Tournament]
    GameAdminBase = admin.ModelAdmin[Game]
    TeamAdminBase = admin.ModelAdmin[Team]
    VidMetadataAdminBase = admin.ModelAdmin[VideoMetadata]
    TmpImageAdminBase = admin.ModelAdmin[TmpImage]
    YTVideoAdminBase = admin.ModelAdmin[YTVideo]
    CutAdminBase = admin.ModelAdmin[Cut]
    VideoAdminBase = admin.ModelAdmin[Video]
    VideoFileAdminBase = admin.ModelAdmin[VideoFile]
    VideoFileInlineBase = admin.TabularInline[VideoFile, Video]
    ActionsMixinBase = admin.ModelAdmin[Any]
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
    VideoFileInlineBase = admin.TabularInline  # type: ignore[assignment]
    ActionsMixinBase = object  # type: ignore[assignment,misc]


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


class WholeTableActionsMixin(ActionsMixinBase):
    """Run an action on the whole list when nothing is selected.

    Django bails out of an action submitted with an empty selection, so
    ticking every row is normally the only way to cover a table. Here an
    empty selection is read as "everything currently listed": the rows of
    the changelist are injected as the selection, which means any active
    filter or search still narrows it.

    The selection travels in the POST, so this suits tables of a few
    thousand rows -- which is what these are -- not unbounded ones.
    """

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        """Fill an empty action selection with every row on show."""
        submitted_action = request.method == "POST" and request.POST.get("action")
        nothing_selected = not request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)
        if submitted_action and nothing_selected:
            listed = self._listed_pks(request)
            if listed:
                post = request.POST.copy()
                post.setlist(helpers.ACTION_CHECKBOX_NAME, listed)
                # The setter exists; the stubs only describe the immutable getter.
                request.POST = post  # type: ignore[assignment]
        return super().changelist_view(request, extra_context)

    def _listed_pks(self, request: HttpRequest) -> list[str]:
        """Return the pks the changelist would show, filters included."""
        try:
            changelist = self.get_changelist_instance(request)
        except IncorrectLookupParameters:
            # Let the changelist itself report the bad filter.
            return []
        return [
            str(pk)
            for pk in changelist.get_queryset(request).values_list("pk", flat=True)
        ]


class FileOnDiskMixin:
    """Show a VideoFile's disk state as an icon, in a list or in an inline."""

    @admin.display(
        boolean=True, description="fichier present", ordering=ON_DISK_ANNOTATION
    )
    def file_on_disk(self, obj: VideoFile) -> bool:
        """Tell whether the file is really there."""
        return obj.exists_on_disk


class FileOnDiskFilter(admin.SimpleListFilter):
    """Filter video files on whether their file is really on disk."""

    title = "fichier present"
    parameter_name = "on_disk"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:
        """List the two states."""
        _ = request, model_admin
        return [("1", "present"), ("0", "absent")]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[VideoFile]
    ) -> QuerySet[VideoFile]:
        """Stat the selection, then filter on the pks that came back."""
        _ = request
        selected = self.value()
        if selected is None:
            return queryset
        present = cast("VideoFileQuerySet", queryset).on_disk_pks()
        if selected == "1":
            return queryset.filter(pk__in=present)
        return queryset.exclude(pk__in=present)


class VideoFileInline(FileOnDiskMixin, VideoFileInlineBase):
    """Every physical file of a video, listed on the video's own page.

    Read-only: a VideoFile path, size and fps are derived from the render,
    never typed in. Rows can still be removed, to drop a dead one.
    """

    model = VideoFile
    extra = 0
    max_num = 0  # no add form: a path comes from the renderer, never typed in
    can_delete = True
    fields = (
        "change_link",
        "quality",
        "format",
        "path",
        "size",
        "fps",
        "file_on_disk",
    )
    readonly_fields = fields

    @admin.display(description="fichier")
    def change_link(self, obj: VideoFile) -> SafeString | str:
        """Link to the VideoFile page, where the fps check action lives."""
        if obj.pk is None:
            return "-"
        url = reverse("admin:core_videofile_change", args=(obj.pk,))
        return format_html('<a href="{}">#{}</a>', url, obj.pk)


class VideoKindFilter(admin.SimpleListFilter):
    """Filter videos on what owns them, which the model derives on the fly."""

    title = "type"
    parameter_name = "kind"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:
        """List the selectable kinds."""
        _ = request, model_admin
        return [(kind.value, kind.label) for kind in Video.Kind]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[Video]
    ) -> QuerySet[Video]:
        """Translate the selected kind into the matching relation lookup."""
        _ = request
        lookups = {
            Video.Kind.PROXY: {"game__isnull": False},
            Video.Kind.GENERATED_RENDERED: {"cut__isnull": False},
            Video.Kind.ARCHIVE: {
                "game__isnull": True,
                "cut__isnull": True,
                "game_archive__isnull": False,
            },
        }
        selected = self.value()
        if selected is None:
            return queryset
        if selected == Video.Kind.ORPHAN:
            return cast("VideoQuerySet", queryset).orphans()
        return queryset.filter(**lookups[Video.Kind(selected)]).distinct()


@admin.register(Video)
class VideoAdmin(WholeTableActionsMixin, VideoAdminBase):
    """Admin config for Video."""

    list_display = (
        "name",
        "status",
        "video_kind",
        "linked_to",
        "related_game",
        "files_link",
    )
    list_filter = ("status", VideoKindFilter)
    search_fields = ("name",)

    fields = ("name", "status", "uuid", "video_kind", "linked_to", "related_game")
    readonly_fields = ("uuid", "video_kind", "linked_to", "related_game")
    inlines = (VideoFileInline,)
    actions = ("delete_orphan_videos",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Video]:
        """Preload the relations the kind and owner columns walk through."""
        return (
            super()
            .get_queryset(request)
            .select_related("game", "cut", "cut__game")
            .prefetch_related("game_archive", "files")
        )

    @admin.display(description="type")
    def video_kind(self, obj: Video) -> str:
        """Show whether the video is a proxy, a cut render or an archive."""
        return Video.Kind(obj.kind).label

    @admin.display(description="associee a")
    def linked_to(self, obj: Video) -> str:
        """Link to the game or cut this video belongs to."""
        if obj.kind == Video.Kind.ARCHIVE:
            return (
                format_html_join(
                    ", ",
                    "{}",
                    ((self._admin_link(game),) for game in obj.archived_games),
                )
                or self.get_empty_value_display()
            )
        related = obj.owner
        if related is None:
            return self.get_empty_value_display()
        return self._admin_link(related)

    @admin.display(description="match")
    def related_game(self, obj: Video) -> str:
        """Show the game behind the video, through the cut when needed."""
        related = obj.owner
        if isinstance(related, Cut):
            related = related.game
        if related is None:
            return self.get_empty_value_display()
        return self._admin_link(related)

    @admin.display(description="fichiers")
    def files_link(self, obj: Video) -> SafeString:
        """Link to this video's files, filtered in the VideoFile admin."""
        url = reverse("admin:core_videofile_changelist")
        rows = obj.files.all()
        present = sum(1 for row in rows if row.exists_on_disk)
        return format_html(
            '<a href="{}?video__id__exact={}">{} / {} sur le disque</a>',
            url,
            obj.pk,
            present,
            len(rows),
        )

    @admin.action(description="Supprimer les videos orphelines selectionnees")
    def delete_orphan_videos(
        self,
        request: HttpRequest,
        queryset: QuerySet[Video],
    ) -> TemplateResponse | None:
        """Delete the selected videos nothing points at anymore.

        The first pass answers with a confirmation screen listing every
        video, its VideoFile rows and whether each file is really on disk.
        Only what that screen shows is deleted when it is submitted back.
        """
        reports = orphan_videos.collect(cast("VideoQuerySet", queryset))
        if not reports:
            self.message_user(
                request,
                "Aucune video orpheline dans la selection.",
                level=messages.WARNING,
            )
            return None

        clean, with_files = orphan_videos.split(reports)
        if request.POST.get("confirm") != "yes":
            return self._confirm_deletion(request, queryset, clean, with_files)

        delete_files = request.POST.get("delete_files") == "on"
        targets = clean + with_files if delete_files else clean
        removed, errors = orphan_videos.delete(targets, delete_files=delete_files)
        for error in errors:
            self.message_user(request, error, level=messages.ERROR)

        self.message_user(
            request,
            f"{len(targets)} video(s) orpheline(s) supprimee(s), "
            f"{sum(len(report.rows) for report in targets)} ligne(s) VideoFile, "
            f"{removed} fichier(s) efface(s) du disque.",
            level=messages.SUCCESS if targets else messages.WARNING,
        )
        if with_files and not delete_files:
            total = sum(report.bytes_on_disk for report in with_files)
            self.message_user(
                request,
                f"{len(with_files)} video(s) conservee(s) : leurs fichiers sont "
                f"encore sur le disque ({total / 1e9:.2f} Go).",
                level=messages.WARNING,
            )
        return None

    def _confirm_deletion(
        self,
        request: HttpRequest,
        queryset: QuerySet[Video],
        clean: list[OrphanReport],
        with_files: list[OrphanReport],
    ) -> TemplateResponse:
        """Render the screen listing what the deletion would take away."""
        orphan_pks = {report.video.pk for report in clean + with_files}
        context = {
            **self.admin_site.each_context(request),
            "title": "Supprimer les videos orphelines",
            "opts": self.opts,
            "media": self.media,
            "clean": clean,
            "with_files": with_files,
            "total_bytes": sum(report.bytes_on_disk for report in with_files),
            "skipped": [item for item in queryset if item.pk not in orphan_pks],
            "selected": request.POST.getlist(helpers.ACTION_CHECKBOX_NAME),
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "select_across": request.POST.get("select_across", "0"),
            "index": request.POST.get("index", "0"),
        }
        return TemplateResponse(
            request,
            "admin/core/video/delete_orphans_confirmation.html",
            context,
        )

    @staticmethod
    def _admin_link(obj: Game | Cut) -> SafeString:
        """Build a link to another object's admin change page."""
        url = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",  # noqa: SLF001
            args=(obj.pk,),
        )
        return format_html('<a href="{}">{}</a>', url, obj)


@admin.register(VideoFile)
class VideoFileAdmin(FileOnDiskMixin, WholeTableActionsMixin, VideoFileAdminBase):
    """Admin config for VideoFile."""

    list_display = (
        "video__name",
        "path",
        "quality",
        "fps",
        "file_on_disk",
    )
    list_filter = ("quality", "format", FileOnDiskFilter)
    search_fields = ("video__name",)
    fields = ("video", "path", "quality")
    readonly_fields = ("fps",)
    actions = ("check_files_and_refresh_fps",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[VideoFile]:
        """Annotate the disk state, but only when sorting asks for it.

        The annotation stats every row of the table, so it is not something
        to pay for on a page that does not order by it.
        """
        queryset: QuerySet[VideoFile] = super().get_queryset(request)
        queryset = queryset.select_related("video")
        if not self._orders_by_disk(request):
            return queryset
        return queryset.annotate(
            **{
                ON_DISK_ANNOTATION: Case(
                    When(
                        pk__in=cast("VideoFileQuerySet", queryset).on_disk_pks(),
                        then=Value(True),  # noqa: FBT003
                    ),
                    default=Value(False),  # noqa: FBT003
                    output_field=BooleanField(),
                )
            }
        )

    def _orders_by_disk(self, request: HttpRequest) -> bool:
        """Tell whether the changelist is ordering on the disk-state column.

        The ORDER_VAR holds positions in the displayed columns, which is
        list_display shifted by the action checkbox: mirror how the
        changelist builds them rather than hard-coding an index.
        """
        columns = list(self.get_list_display(request))
        if self.get_actions(request):
            columns.insert(0, "action_checkbox")
        if "file_on_disk" not in columns:
            return False
        wanted = str(columns.index("file_on_disk"))
        return any(
            part.rpartition("-")[2] == wanted
            for part in request.GET.get(ORDER_VAR, "").split(".")
        )

    def lookup_allowed(
        self, lookup: str, value: Any, request: HttpRequest | None = None
    ) -> bool:
        """Allow filtering by video, which the Video admin links to.

        `video` is deliberately kept out of `list_filter`: a dropdown of every
        video would be unusable, but the lookup itself has to be permitted.
        """
        if lookup == "video__id__exact":
            return True
        return super().lookup_allowed(lookup, value, request)

    @admin.action(
        description="Verifier les fichiers, reparer les chemins, mettre a jour les fps"
    )
    def check_files_and_refresh_fps(
        self,
        request: HttpRequest,
        queryset: QuerySet[VideoFile],
    ) -> None:
        """Probe the selected files and store the frame rate ffprobe reports."""
        outcomes: Counter[str] = Counter()
        broken: list[str] = []

        for video_file in queryset.select_related("video"):
            outcome, _ = video_file.check_file()
            outcomes[outcome] += 1
            if outcome in {
                VideoFile.FileCheck.NO_PATH,
                VideoFile.FileCheck.MISSING,
                VideoFile.FileCheck.PROBE_FAILED,
            }:
                broken.append(
                    f"#{video_file.pk} {video_file} "
                    f"({VideoFile.FileCheck(outcome).label}): "
                    f"{video_file.path or '-'}"
                )

        summary = ", ".join(
            f"{count} {VideoFile.FileCheck(outcome).label}"
            for outcome, count in sorted(outcomes.items())
        )
        self.message_user(
            request,
            f"{sum(outcomes.values())} fichier(s) verifie(s) : {summary}",
            level=messages.WARNING if broken else messages.SUCCESS,
        )
        for line in broken[:MAX_REPORTED_BROKEN_FILES]:
            self.message_user(request, line, level=messages.ERROR)
        if len(broken) > MAX_REPORTED_BROKEN_FILES:
            self.message_user(
                request,
                f"... et {len(broken) - MAX_REPORTED_BROKEN_FILES} autre(s) "
                f"fichier(s) en erreur, filtrer sur 'fichier present' pour les voir.",
                level=messages.ERROR,
            )


admin.site.register(RenderQueueItemCut)
admin.site.register(RenderQueueItemProxy)
admin.site.register(RenderQueueItemArchive)
admin.site.register(RenderQueueItemGenCut)
