"""Serializers for the API."""

from collections.abc import Sequence
from typing import Any, TypeVar

from rest_framework import serializers

from game_edit.models import Cut, Game, Team, Tournament
from miniatures.models import TeamLogo, TmpImage, VideoMetadata, YTVideo

Model = Cut | Game | Team | Tournament | TeamLogo | TmpImage | VideoMetadata | YTVideo

T = TypeVar("T", bound=Model)


class HALMixin(serializers.ModelSerializer[T]):
    """Generate a HAL representation of a model.

    All links go in the `_links` field.
    Deletes the `url` field.
    """

    hal_embedded: dict[str, type[serializers.Serializer]] = {}

    def to_representation(self, instance: T) -> dict[str, Any]:
        """Generate the HAL representation."""
        data = super().to_representation(instance)
        links: dict[str, dict[str, str] | list[dict[str, str]]] = {}

        # self depuis 'url' (puis on le retire de la payload)
        if data.get("url"):
            links["self"] = {"href": data.pop("url")}

        # Collecte des liens pour HyperlinkedIdentityField et HyperlinkedRelatedField
        for name, field in self.fields.items():
            if name == "url":
                continue
            try:
                is_identity = isinstance(field, serializers.HyperlinkedIdentityField)
                is_related = isinstance(field, serializers.HyperlinkedRelatedField)
            except Exception:
                is_identity = False
                is_related = False

            if is_identity or is_related:
                if name in data:
                    href_value = data.pop(name)
                    if href_value is None:
                        continue
                    if isinstance(href_value, list | tuple):
                        links[name] = [{"href": v} for v in href_value if v]
                    else:
                        links[name] = {"href": href_value}

        if links:
            data["_links"] = links
            
        # add _embedded from hal_embedded
        embedded: dict[str, Any] = {}
        for name, serializer_cls in (getattr(self, "hal_embedded", {}) or {}).items():
            # Ignore si le champ n'existe pas sur le serializer ou l'instance
            if name not in self.fields:
                continue
            value = getattr(instance, name, None)
            if value is None:
                # rien à embarquer
                continue

            # Détermine si la relation est multiple (ManyRelatedManager / QuerySet / collection)
            is_many_relation = False
            if hasattr(value, "all") and callable(value.all):
                # Relation inversée ou many-to-many
                value = value.all()
                is_many_relation = True
            elif isinstance(value, (list, tuple, set)):
                is_many_relation = True

            try:
                serializer = serializer_cls(value, many=is_many_relation, context=self.context)
                embedded[name] = serializer.data
                # Retire le champ original de la payload si présent, pour éviter duplication
                data.pop(name, None)
            except Exception:
                # En cas d'erreur d'embarquement, on laisse la représentation telle quelle
                continue

        if embedded:
            data["_embedded"] = embedded

        return data

        return data


class TeamLogoSerializer(
    HALMixin[TeamLogo], serializers.HyperlinkedModelSerializer[TeamLogo]
):
    """TeamLogo serializer."""

    teams = serializers.HyperlinkedIdentityField(view_name="teamlogo-teams")

    class Meta:
        """Meta."""

        model = TeamLogo
        fields: Sequence[str] = ["url", "pk", "name", "short_name", "image", "teams"]


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


    class Meta:
        """Meta."""

        model = YTVideo
        fields: Sequence[str] = [
            "url",
            "pk",
            "title",
            "video_id",
            "linked_video_id",
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
    videos = serializers.HyperlinkedIdentityField(view_name="tournament-videos")

    hal_embedded = {"videos": VideoMetadataSerializer}

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
            "videos",
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
    hal_embedded = {"logo": TeamLogoSerializer}

    class Meta:
        """Meta."""

        model = Team
        fields: Sequence[str] = ["url", "pk", "logo", "name", "slug"]
