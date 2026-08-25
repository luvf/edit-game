"""Serializers for the API."""

import json
import sys
from collections.abc import Sequence
from pydoc import locate
from typing import Any, ClassVar, TypeVar

from django.conf import settings
from django.core.files.base import ContentFile
from django.template.defaultfilters import slugify
from rest_framework import serializers

from core.models.cut import Cut
from core.models.game import Game
from core.models.media import TmpImage, VideoMetadata, YTVideo
from core.models.render_queue.base import (
    RenderQueueItemBase as RenderQueueItem,
)
from core.models.tournament import Team, Tournament
from core.models.video import Video

Model = (
    Cut
    | Game
    | Tournament
    | Team
    | TmpImage
    | VideoMetadata
    | YTVideo
    | RenderQueueItem
    | Video
)

T = TypeVar("T", bound=Model)


class HALMixin(serializers.ModelSerializer[T]):
    """Generate a HAL representation of a model.

    All links go in the `_links` field.
    Deletes the `url` field.
    """

    default_hal_embedded: ClassVar[dict[str, str]] = {}

    def __init__(
        self, *args: Any, hal_embedded: dict[str, str] | None = None, **kwargs: Any
    ) -> None:
        """Init."""
        super().__init__(*args, **kwargs)
        if hal_embedded is not None:
            self.hal_embedded = hal_embedded
        else:
            self.hal_embedded = self.default_hal_embedded

    def _build_links(
        self, data: dict[str, Any]
    ) -> dict[str, dict[str, str] | list[dict[str, str]]]:
        """Builds _links section of HAL format."""
        links: dict[str, dict[str, str] | list[dict[str, str]]] = {}

        if data.get("url"):
            links["self"] = {"href": data.pop("url")}

        for name, field in self.fields.items():
            if name == "url":
                continue

            is_link_field = isinstance(
                field,
                (
                    serializers.HyperlinkedIdentityField
                    | serializers.HyperlinkedRelatedField
                ),
            )

            if is_link_field and name in data:
                href_value = data.pop(name)
                if href_value is None:
                    continue

                if isinstance(href_value, (list | tuple)):
                    links[name] = [{"href": v} for v in href_value if v]
                else:
                    links[name] = {"href": href_value}
        return links

    def _resolve_serializer_class(
        self, serializer_cls: str
    ) -> None | type[serializers.Serializer[T]]:
        """Resolve class serializer class."""
        current_module = sys.modules[self.__module__]
        namespace = vars(current_module)
        cls = namespace.get(serializer_cls)
        if isinstance(cls, type) and issubclass(cls, serializers.Serializer):
            return cls
        cls = locate(serializer_cls)

        print(f"Unable to resolve {serializer_cls} ")
        return None

    def _build_embedded(
        self,
        instance: T,
        data: dict[str, Any],
        *,
        allowed: set[str] | None = None,
    ) -> dict[str, Any]:
        """Builds _ebmedded section of HAL format."""
        embedded: dict[str, Any] = {}

        for name, serializer_cls in (getattr(self, "hal_embedded", {}) or {}).items():
            if allowed is not None and name not in allowed:
                continue
            value = getattr(instance, name, None)
            if value is None:
                continue
            is_many_relation = (
                hasattr(value, "all")
                and callable(value.all)
                or isinstance(value, (list | tuple | set))
            )

            if is_many_relation and hasattr(value, "all"):
                value = value.all()

            try:
                serializer_ref = self._resolve_serializer_class(serializer_cls)
                if serializer_ref and issubclass(serializer_ref, HALMixin):
                    serializer = serializer_ref(
                        value,
                        hal_embedded={},
                        many=is_many_relation,
                        context=self.context,
                    )
                    embedded[name] = serializer.data
                    data.pop(name, None)
            except Exception as e:
                print(f"not able to create embedded object {name}, exception: {e}")

        return embedded

    def to_representation(self, instance: T) -> dict[str, Any]:
        """Generate the HAL representation."""
        data = super().to_representation(instance)
        request = self.context.get("request") if hasattr(self, "context") else None
        params = request.query_params if request is not None else {}
        no_embed = str(params.get("no_embed", "")).lower() in {"1", "true", "yes"}
        embed_param = str(params.get("embed", "")).strip()
        fields_param = str(params.get("fields", "")).strip()
        allowed_embeds = None
        if embed_param:
            allowed_embeds = {
                item.strip() for item in embed_param.split(",") if item.strip()
            }

        # Construction des liens
        links = self._build_links(data)
        if links:
            data["_links"] = links

        # Construction des objets embarqués
        if not no_embed:
            embedded = self._build_embedded(instance, data, allowed=allowed_embeds)
            if embedded:
                data["_embedded"] = embedded

        if fields_param:
            allowed_fields = {
                item.strip() for item in fields_param.split(",") if item.strip()
            }
            filtered: dict[str, Any] = {}
            for key, value in data.items():
                if key in allowed_fields or key in {"_links", "_embedded"}:
                    filtered[key] = value
            data = filtered

        return data


class VideoMetadataSerializer(
    HALMixin[VideoMetadata], serializers.HyperlinkedModelSerializer[VideoMetadata]
):
    """VideoMetadata serializer."""

    reset_url = serializers.HyperlinkedIdentityField(view_name="videometadata-reset")
    upload_description = serializers.HyperlinkedIdentityField(
        view_name="videometadata-upload-description"
    )
    upload_miniature = serializers.HyperlinkedIdentityField(
        view_name="videometadata-upload-miniature"
    )
    find_ytvid = serializers.HyperlinkedIdentityField(
        view_name="videometadata-find-ytvid"
    )
    generate_miniature = serializers.HyperlinkedIdentityField(
        view_name="videometadata-generate-miniature"
    )
    linked_yt_videos = serializers.HyperlinkedIdentityField(
        view_name="videometadata-linked-yt-videos",
    )
    set_yt_video = serializers.HyperlinkedIdentityField(
        view_name="videometadata-set-yt-video",
    )
    reset_title_description = serializers.HyperlinkedIdentityField(
        view_name="videometadata-reset-title-description"
    )

    default_hal_embedded: ClassVar[dict[str, str]] = {
        "linked_yt_videos": "YTVideoSerializer",
        "tournament": "TournamentSerializer",
        "team1": "TeamSerializer",
        "team2": "TeamSerializer",
    }

    class Meta:
        """Meta."""

        model = VideoMetadata
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "tournament",
            "time_code",
            "miniature_x_offset",
            "miniature_y_offset",
            "miniature_zoom",
            "base_image",
            "miniature_image",
            "team1",
            "team2",
            "video_name",
            "description",
            "publication_date",
            "reset_url",
            "upload_description",
            "upload_miniature",
            "find_ytvid",
            "generate_miniature",
            "linked_yt_videos",
            "set_yt_video",
            "reset_title_description",
        ]


class TmpImageSerializer(
    HALMixin[TmpImage], serializers.HyperlinkedModelSerializer[TmpImage]
):
    """TmpImage serializer."""

    class Meta:
        """Meta."""

        model = TmpImage
        fields: Sequence[str] = ["url", "pk", "name", "image"]


class YTVideoSerializer(
    HALMixin[YTVideo], serializers.HyperlinkedModelSerializer[YTVideo]
):
    """YTVideo serializer."""

    default_hal_embedded: ClassVar[dict[str, str]] = {
        "linked_video": "VideoMetadataSerializer"
    }

    class Meta:
        """Meta."""

        model = YTVideo
        fields: Sequence[str] = [
            "url",
            "pk",
            "title",
            "video_id",
            "linked_video",
            "publication_date",
            "privacy_status",
        ]


class TournamentSerializer(
    HALMixin[Tournament], serializers.HyperlinkedModelSerializer[Tournament]
):
    """Tournament serializer."""

    games = serializers.HyperlinkedIdentityField(view_name="tournament-games")
    sync_videos = serializers.HyperlinkedIdentityField(
        view_name="tournament-sync-videos"
    )
    youtube_update = serializers.HyperlinkedIdentityField(
        view_name="tournament-youtube-update"
    )
    archive = serializers.HyperlinkedIdentityField(view_name="tournament-archive")
    is_archived = serializers.SerializerMethodField()
    video_metadatas = serializers.HyperlinkedIdentityField(
        view_name="tournament-videos"
    )
    rendered = serializers.HyperlinkedIdentityField(view_name="tournament-rendered")
    source_files = serializers.HyperlinkedIdentityField(
        view_name="tournament-source-files"
    )
    create_game = serializers.HyperlinkedIdentityField(
        view_name="tournament-create-game"
    )
    generate_games = serializers.HyperlinkedIdentityField(
        view_name="tournament-generate-games"
    )
    tournament_dir = serializers.CharField(write_only=True)
    drive_dir = serializers.CharField(write_only=True)

    default_hal_embedded: ClassVar[dict[str, str]] = {}

    class Meta:
        """Meta."""

        model = Tournament
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "short_name",
            "date",
            "games",
            "place",
            "JTR",
            "tugeny_link",
            "color",
            "slug",
            "is_archived",
            "generate_games",
            "create_game",
            "video_metadatas",
            "rendered",
            "source_files",
            "sync_videos",
            "youtube_update",
            "archive",
            "tournament_dir",
            "drive_dir",
        ]

    def get_is_archived(self, obj: Tournament) -> bool:
        """Check if tournament is archived based on drive directory."""
        return obj.drive_dir == str(settings.TOURNAMENTS_ARCHIVE_DIR)

    def to_representation(self, instance: Tournament) -> dict[str, Any]:
        """Remove archive link if tournament is archived."""
        data = super().to_representation(instance)
        if self.get_is_archived(instance):
            links = data.get("_links")
            if isinstance(links, dict):
                links.pop("archive", None)
        return data

    def create(self, validated_data: Any) -> Tournament:
        """Create a new tournament instance."""
        new_tournament = Tournament(
            name=validated_data.get("name"),
            short_name=validated_data.get("short_name", validated_data.get("name")),
            date=validated_data.get("date"),
            place=validated_data.get("place") or "",
            JTR=validated_data.get("JTR") or "",
            tugeny_link=validated_data.get("tugeny_link") or "",
            color=validated_data.get("color") or "#0000",
            slug=slugify(validated_data.get("name")),
            drive_dir=validated_data.get("drive_dir"),
            tournament_dir=validated_data.get("tournament_dir"),
        )
        new_tournament.save()
        return new_tournament


class GameSerializer(HALMixin[Game], serializers.HyperlinkedModelSerializer[Game]):
    """Game serializer."""

    cuts = serializers.HyperlinkedIdentityField(view_name="game-cuts")
    create_cut = serializers.HyperlinkedIdentityField(view_name="game-create-cut")
    generate_proxy = serializers.HyperlinkedIdentityField(
        view_name="game-generate-proxy"
    )
    create_archive = serializers.HyperlinkedIdentityField(
        view_name="game-create-archive"
    )

    default_hal_embedded: ClassVar[dict[str, str]] = {
        "tournament": "TournamentSerializer",
        "team1": "TeamSerializer",
        "team2": "TeamSerializer",
        "video_proxy": "VideoSerializer",
    }

    class Meta:
        """Meta."""

        model = Game
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "files",
            "tournament",
            "team1",
            "team2",
            "json_file",
            "cuts",
            "create_cut",
            "generate_proxy",
            "create_archive",
            "video_proxy",
        ]


class CutSerializer(HALMixin[Cut], serializers.HyperlinkedModelSerializer[Cut]):
    """Cut serializer."""

    render = serializers.HyperlinkedIdentityField(view_name="cut-render")
    gen_from_file = serializers.HyperlinkedIdentityField(view_name="cut-gen-from-file")
    gen_from_rendered = serializers.HyperlinkedIdentityField(
        view_name="cut-gen-from-rendered"
    )
    default_hal_embedded: ClassVar[dict[str, str]] = {
        "rendered_video": "VideoSerializer",
    }

    class Meta:
        """Meta."""

        model = Cut
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "type_cut",
            "json_file",
            "rendered_video",
            "game",
            "slug",
            "render",
            "gen_from_file",
            "gen_from_rendered",
        ]

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Let json_file bypass FileField validation when it's raw JSON, not an upload.

        DRF's auto-generated FileField rejects any non-file value before
        `update()` ever runs, so a plain str/dict/list payload for json_file
        must be pulled out here and re-injected after the base validation.
        """
        raw_json_file = None
        if "json_file" in data and not hasattr(data.get("json_file"), "read"):
            data = data.copy()
            raw_json_file = data.pop("json_file")
        validated: dict[str, Any] = super().to_internal_value(data)
        if raw_json_file is not None:
            validated["json_file"] = raw_json_file
        return validated

    def update(self, instance: Cut, validated_data: dict[str, Any]) -> Cut:
        """Update a cut, handling JSON payloads for json_file."""
        json_file_value = validated_data.pop("json_file", None)

        # Si le client envoie un JSON déjà parsé (dict/list), on le sérialise
        if isinstance(json_file_value, dict | list):
            json_file_value = json.dumps(json_file_value, ensure_ascii=False)

        # Cas spécial : on reçoit une string => on la transforme en fichier
        if isinstance(json_file_value, str):
            try:
                json.loads(json_file_value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError(
                    {"json_file": "Le contenu fourni n'est pas un JSON valide."}
                ) from exc

            filename = f"cut_{instance.pk}_data.json"
            content = ContentFile(json_file_value.encode("utf-8"))
            instance.json_file.save(filename, content, save=False)

        # Cas normal : on reçoit un vrai fichier uploadé
        elif json_file_value is not None:
            instance.json_file = json_file_value

        # Appliquer les autres champs
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class RenderQueueItemSerializer(
    HALMixin[RenderQueueItem], serializers.HyperlinkedModelSerializer[RenderQueueItem]
):
    """Render queue serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="renderqueue-detail")
    run = serializers.HyperlinkedIdentityField(view_name="renderqueue-run")
    reset = serializers.HyperlinkedIdentityField(view_name="renderqueue-reset")
    cut = serializers.SerializerMethodField()
    game = serializers.SerializerMethodField()
    cut_name = serializers.CharField(source="cut.name", read_only=True)
    game_name = serializers.CharField(source="game.name", read_only=True)
    metadata = serializers.SerializerMethodField()
    command = serializers.SerializerMethodField()

    def get_metadata(self, obj: RenderQueueItem) -> str:
        """Return metadata for ffmpeg items, empty otherwise."""
        return obj.concrete().metadata if obj.concrete() else ""

    def get_command(self, obj: RenderQueueItem) -> str:
        """Return command for ffmpeg items, empty otherwise."""
        return obj.concrete().command_parameters if obj.concrete() else ""

    def get_cut(self, obj: RenderQueueItem) -> int | None:
        """Return the cut id for a queue item."""
        return obj.cut.pk if obj.cut else None

    def get_game(self, obj: RenderQueueItem) -> int | None:
        """Return the game id for a queue item."""
        return obj.game.pk if obj.game else None

    class Meta:
        """Meta."""

        model = RenderQueueItem
        fields: Sequence[str] = [
            "url",
            "run",
            "reset",
            "pk",
            "job_type",
            "cut",
            "cut_name",
            "game",
            "game_name",
            "metadata",
            "status",
            "command",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        ]


class TeamSerializer(HALMixin[Team], serializers.HyperlinkedModelSerializer[Team]):
    """Team serializer."""

    class Meta:
        """Meta."""

        model = Team
        fields: Sequence[str] = ["url", "pk", "name", "short_name", "image", "slug"]


class VideoSerializer(HALMixin[Video], serializers.HyperlinkedModelSerializer[Video]):
    """Video serializer."""

    owner_type = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()
    qualities = serializers.SerializerMethodField()

    class Meta:
        """Meta."""

        model = Video
        fields: Sequence[str] = [
            "pk",
            "url",
            "duration",
            "owner_type",
            "files",
            "qualities",
            "cut",
            "game",
        ]
        read_only_fields = fields

    def get_owner_type(self, obj: Video) -> str | None:
        """Return the type of the owner (game or cut)."""
        try:
            if obj.game:
                return "game"
        except AttributeError:
            pass
        try:
            if obj.cut:
                return "cut"
        except AttributeError:
            pass
        return None

    def get_files(self, obj: Video) -> dict[str, dict[str, Any]]:
        """Return physical files indexed by quality."""
        files: dict[str, dict[str, Any]] = {}

        for video_file in obj.files.all():
            url = video_file.url
            if len(url) > 0:
                files[video_file.quality] = {
                    "url": url,
                    "format": video_file.format,
                }

        return files

    def get_qualities(self, obj: Video) -> list[str]:
        """Return available qualities."""
        return list(obj.files.values_list("quality", flat=True).distinct())
