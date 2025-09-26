"""Serializers for the API."""

from collections.abc import Sequence
from pydoc import locate
from typing import Any, TypeVar

from rest_framework import serializers

from game_edit.models import Cut, Game, Team, Tournament
from miniatures.models import TeamLogo, TmpImage, VideoMetadata, YTVideo

Model = Cut | Game | Team | Tournament | TeamLogo | TmpImage | VideoMetadata | YTVideo

T = TypeVar("T", bound=Model)


def normalize_to_class(value, namespace: dict) -> type:
    if isinstance(value, type):
        return value
    if isinstance(value, str):
        cls = locate(value)
        if cls is not None:
            return cls
        obj = namespace.get(value)
        if isinstance(obj, type):
            return obj
    raise TypeError(f"Impossible de résoudre la classe depuis: {value!r}")


class HALMixin(serializers.ModelSerializer[T]):
    """Generate a HAL representation of a model.

    All links go in the `_links` field.
    Deletes the `url` field.
    """

    hal_embedded: dict[str, type[serializers.Serializer]] = {}

    def __init__(self, *args, **kwargs):
        """Init. ensure deepness parameter"""
        if "hal_embedded" in kwargs and isinstance(
            kwargs["hal_embedded"], type(self.hal_embedded)
        ):
            self.hal_embedded = kwargs.pop("hal_embedded")
        super().__init__(*args, **kwargs)

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
                    serializers.HyperlinkedIdentityField,
                    serializers.HyperlinkedRelatedField,
                ),
            )

            if is_link_field and name in data:
                href_value = data.pop(name)
                if href_value is None:
                    continue

                if isinstance(href_value, (list, tuple)):
                    links[name] = [{"href": v} for v in href_value if v]
                else:
                    links[name] = {"href": href_value}
        return links

    def _resolve_serializer_class(self, serializer_cls: type | str) -> type:
        """Resolve class serializer class."""
        try:
            import sys

            current_module = sys.modules[self.__module__]
            namespace = vars(current_module)
            return normalize_to_class(serializer_cls, namespace)
        except (TypeError, AttributeError):
            return serializer_cls

    def _build_embedded(self, instance: T, data: dict[str, Any]) -> dict[str, Any]:
        """Builds _ebmedded section of HAL format."""
        embedded: dict[str, Any] = {}

        for name, serializer_cls in (getattr(self, "hal_embedded", {}) or {}).items():
            value = getattr(instance, name, None)
            if value is None:
                continue
            is_many_relation = (
                hasattr(value, "all")
                and callable(value.all)
                or isinstance(value, (list, tuple, set))
            )

            if is_many_relation and hasattr(value, "all"):
                value = value.all()

            try:
                serializer_ref = self._resolve_serializer_class(serializer_cls)
                serializer = serializer_ref(
                    value, many=is_many_relation, context=self.context, hal_embedded={}
                )
                embedded[name] = serializer.data
                data.pop(name, None)
            except:
                pass

        return embedded

    def to_representation(self, instance: T) -> dict[str, Any]:
        """Generate the HAL representation."""
        data = super().to_representation(instance)

        # Construction des liens
        links = self._build_links(data)
        if links:
            data["_links"] = links

        # Construction des objets embarqués
        embedded = self._build_embedded(instance, data)
        if embedded:
            data["_embedded"] = embedded

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
    reset_title_description = serializers.HyperlinkedIdentityField(
        view_name="videometadata-reset-title-description"
    )

    hal_embedded = {
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
            "tc",
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

    hal_embedded = {"linked_video": "VideoMetadataSerializer"}

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
    video_metadatas = serializers.HyperlinkedIdentityField(
        view_name="tournament-videos"
    )

    hal_embedded = {"video_metadatas": "VideoMetadataSerializer"}

    class Meta:
        """Meta."""

        model = Tournament
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "date",
            "games",
            "place",
            "JTR",
            "tugeny_link",
            "color",
            "slug",
            "video_metadatas",
            "sync_videos",
            "youtube_update",
        ]


class GameSerializer(HALMixin[Game], serializers.HyperlinkedModelSerializer[Game]):
    """Game serializer."""

    cuts = serializers.HyperlinkedIdentityField(view_name="game-cuts")

    class Meta:
        """Meta."""

        model = Game
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "source_name",
            "tournament",
            "rendered",
            "team1",
            "team2",
            "json_file",
            "source_proxy",
            "cuts",
        ]


class CutSerializer(HALMixin[Cut], serializers.HyperlinkedModelSerializer[Cut]):
    """Cut serializer."""

    class Meta:
        """Meta."""

        model = Cut
        fields: Sequence[str] = [
            "url",
            "pk",
            "name",
            "type_cut",
            "json_file",
            "game",
            "slug",
        ]


class TeamSerializer(HALMixin[Team], serializers.HyperlinkedModelSerializer[Team]):
    """Team serializer."""

    hal_embedded = {"logo": "TeamLogoSerializer"}

    class Meta:
        """Meta."""

        model = Team
        fields: Sequence[str] = ["url", "pk", "logo", "name", "slug"]


class TeamLogoSerializer(
    HALMixin[TeamLogo], serializers.HyperlinkedModelSerializer[TeamLogo]
):
    """TeamLogo serializer."""

    teams = serializers.HyperlinkedIdentityField(view_name="teamlogo-teams")
    hal_embedded = {"teams": "TeamSerializer"}

    class Meta:
        """Meta."""

        model = TeamLogo
        fields: Sequence[str] = ["url", "pk", "name", "short_name", "image", "teams"]
