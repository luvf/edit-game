"""Serializers for the API."""

import json
import sys
from collections.abc import Sequence
from pydoc import locate
from typing import Any, ClassVar, TypeVar

from django.core.files.base import ContentFile
from rest_framework import serializers

from core.models import Cut, Game, Team, TmpImage, Tournament, VideoMetadata, YTVideo

Model = Cut | Game | Tournament | Team | TmpImage | VideoMetadata | YTVideo

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
    video_metadatas = serializers.HyperlinkedIdentityField(
        view_name="tournament-videos"
    )
    generate_games = serializers.HyperlinkedIdentityField(
        view_name="tournament-generate-games"
    )

    default_hal_embedded: ClassVar[dict[str, str]] = {
        "video_metadatas": "VideoMetadataSerializer"
    }

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
            "generate_games",
            "video_metadatas",
            "sync_videos",
            "youtube_update",
        ]


class GameSerializer(HALMixin[Game], serializers.HyperlinkedModelSerializer[Game]):
    """Game serializer."""

    cuts = serializers.HyperlinkedIdentityField(view_name="game-cuts")

    generate_proxy = serializers.HyperlinkedIdentityField(
        view_name="game-generate-proxy"
    )

    default_hal_embedded: ClassVar[dict[str, str]] = {
        "tournament": "TournamentSerializer",
        "team1": "TeamSerializer",
        "team2": "TeamSerializer",
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
            "rendered",
            "team1",
            "team2",
            "json_file",
            "source_proxy",
            "cuts",
            "generate_proxy",
        ]


class CutSerializer(HALMixin[Cut], serializers.HyperlinkedModelSerializer[Cut]):
    """Cut serializer."""

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

    class Meta:
        """Meta."""

        model = Team
        fields: Sequence[str] = ["url", "pk", "name", "short_name", "image", "slug"]
