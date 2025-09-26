"""Api Views."""

import contextlib
import random
import urllib.parse
from collections.abc import Sequence
from http import HTTPMethod
from typing import cast

from django.db.models import Q
from django.http import Http404
from django.urls import resolve
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    AllowAny,
    BasePermission,
    OperandHolder,
    SingleOperandHolder,
)
from rest_framework.request import Request
from rest_framework.response import Response

from api.serializers import (
    CutSerializer,
    GameSerializer,
    TeamLogoSerializer,
    TeamSerializer,
    TmpImageSerializer,
    TournamentSerializer,
    VideoMetadataSerializer,
    YTVideoSerializer,
)

# Create your views here.
from game_edit.models import Cut, Game, Team, Tournament
from jugger_video_manipulation.build_miniature import get_video_file_names
from miniatures.models import TeamLogo, TmpImage, VideoMetadata, YTVideo

type PermissionClass = type[BasePermission] | OperandHolder | SingleOperandHolder


class TeamLogoViewSet(viewsets.ModelViewSet[TeamLogo]):
    """Team Logo viewset.

    Actions:
        -teams: returns the teams associated with this logo.
    """

    serializer_class = TeamLogoSerializer
    queryset = TeamLogo.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    @action(detail=True, methods=[HTTPMethod.GET], url_path="teams")
    def teams(self, request: Request, pk: str | None = None) -> Response:
        """Returns the teams associated with this logo."""
        _ = pk, request
        logo = self.get_object()
        qs = Team.objects.filter(logo=logo).order_by("name")
        serializer = TeamSerializer(
            qs,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)


class VideoMetadataViewSet(viewsets.ModelViewSet[VideoMetadata]):
    """Video Metadata viewset.

    Actions:
        - reset[PATCH]: resets all the metadata.
        - upload_description[PATCH]: updates the description of the linked YouTube video.
        - upload_miniature[PATCH]: updates only the miniature (thumbnail) of linked YouTube video.
        - find_ytvid[PATCH]: links this video to the first YTVideo found that matches.
        - linked_yt_videos[GET]: returns all the YTVideo linked to this VideoMetadata.
        - generate_miniature[POST]: generates the miniature.
        - reset_title_description[PATCH]: resets all the metadata and generates the miniature.

    """

    serializer_class = VideoMetadataSerializer
    queryset = VideoMetadata.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    @action(detail=True, methods=[HTTPMethod.PATCH], url_path="reset")
    def reset(self, request: Request, pk: str | None = None) -> Response:
        """Reinitialize the metadata."""
        _ = pk, request
        instance: VideoMetadata = self.get_object()
        instance.reset_metadata()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.PATCH], url_path="upload-description")
    def upload_description(self, request: Request, pk: str | None = None) -> Response:
        """Update the description of the linked YouTube video.

        Does Not update the Miniature..
        """
        _ = pk, request
        instance: VideoMetadata = self.get_object()
        yt_vid = instance.YTlink.first()
        if not yt_vid:
            return Response(
                {"detail": "Aucune ressource YouTube liée à cette vidéo."}, status=404
            )
        yt_vid.upload_description()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.PATCH], url_path="upload-miniature")
    def upload_miniature(self, request: Request, pk: str | None = None) -> Response:
        """Updates only the miniature (thumbnail) of linked YouTube video.

        Does Not update the title/description/status.
        """
        _ = pk, request
        instance: VideoMetadata = self.get_object()
        yt_vid = instance.YTlink.first()
        if not yt_vid:
            return Response(
                {"detail": "Aucune ressource YouTube liée à cette vidéo."}, status=404
            )
        yt_vid.upload_miniature()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.PATCH], url_path="find-ytvid")
    def find_ytvid(self, request: Request, pk: str | None = None) -> Response:
        """Links this video to the first YTVideo found that matches.

        The match is made by the name of the video without the extension.
        """
        _ = pk, request
        instance: VideoMetadata = self.get_object()

        title_candidate_1 = (instance.name or "").split(".")[0]
        title_candidate_2 = instance.video_name or ""

        vid_qs = YTVideo.objects.filter(
            Q(linkedVideo__isnull=True)
            & (Q(title=title_candidate_1) | Q(title=title_candidate_2))
        )
        if vid_qs.exists():
            yt = cast(YTVideo, vid_qs.first())
            yt.linked_video = instance
            yt.save()

        return Response({})

    @action(detail=True, methods=[HTTPMethod.GET], url_path="linked_yt_videos")
    def linked_yt_videos(self, request: Request, pk: str | None = None) -> Response:
        """Retourne toutes les vidéos YouTube liées à ce VideoMetadata."""
        _ = pk
        instance = self.get_object()
        qs = YTVideo.objects.filter(linked_video=instance)
        serializer = YTVideoSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @action(
        detail=True,
        methods=[HTTPMethod.POST],
        url_path="generate_miniature",
    )
    def generate_miniature(self, request: Request, pk: str | None = None) -> Response:
        """Generate the miniature.

        - POST: génère la miniature (xoffset, yoffset, zoom)
                et renvoie les URLs + métadonnées YT.
        """
        _ = pk
        instance: VideoMetadata = self.get_object()

        def team_from_url(url: str) -> TeamLogo:
            path = urllib.parse.urlparse(url).path
            resolved_func, unused_args, resolved_kwargs = resolve(path)
            return cast(
                TeamLogo,
                resolved_func.cls().get_queryset().get(id=resolved_kwargs["pk"]),
            )

        # Paramètres de génération
        xoffset = float(request.data.get("xoffset", 1))
        yoffset = float(request.data.get("yoffset", 0))
        zoom = float(request.data.get("zoom", 1))
        reset_metadata = False
        # Met à jour éventuellement le time code si fourni
        if "timeCode" in request.data:
            with contextlib.suppress(TypeError, ValueError):
                instance.tc = float(request.data.get("timeCode", instance.tc))
                instance.save()
        if "team1" in request.data:
            with contextlib.suppress(TypeError, ValueError, Http404):
                new_team = team_from_url(request.data["team1"])
                if new_team != instance.team1:
                    reset_metadata = True
                instance.team1 = new_team
                instance.save()
        if "team2" in request.data:
            with contextlib.suppress(TypeError, ValueError, Http404):
                new_team = team_from_url(request.data["team2"])
                if new_team != instance.team1:
                    reset_metadata = True
                instance.team2 = new_team
                instance.save()
        if reset_metadata:
            instance.reset_description()
            instance.reset_vid_name()
            instance.save()
        # Génère la miniature
        instance.generate_miniature(x_offset=xoffset, y_offset=yoffset, zoom=zoom)
        serializer = VideoMetadataSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.PATCH], url_path="reset_title_description")
    def reset_title_description(
        self, request: Request, pk: str | None = None
    ) -> Response:
        """Déclenche la génération des métadonnées et les renvoie."""
        _ = pk
        instance: VideoMetadata = self.get_object()
        instance.reset_metadata()
        serializer = VideoMetadataSerializer(instance, context={"request": request})
        return Response(serializer.data)


class TmpImageViewSet(viewsets.ModelViewSet[TmpImage]):
    """ViewSet pour les images temporaires."""

    serializer_class = TmpImageSerializer
    queryset = TmpImage.objects.all()


class YTVideoViewSet(viewsets.ModelViewSet[YTVideo]):
    """yt_video viewset."""

    serializer_class = YTVideoSerializer
    queryset = YTVideo.objects.all()


class TournamentsViewSet(viewsets.ModelViewSet[Tournament]):
    """Tournament viewset.

    Actions:
        - games[GET]: returns the games associated with this tournament.
        - sync_videos[POST]:get the videos associated with this tournament.
        - videos[GET]: returns the videos associated with this tournament.
        - youtube_update[POST]: Trigger update of YouTube videos.
    """

    serializer_class = TournamentSerializer
    queryset = Tournament.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    @action(detail=True, methods=[HTTPMethod.GET], url_path="games")
    def games(self, request: Request, pk: str | None = None) -> Response:
        """Get the games associated with this tournament."""
        _ = pk, request
        tournament = self.get_object()
        qs = Game.objects.filter(tournament=tournament).order_by("name")
        serializer = GameSerializer(
            qs, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="sync_videos")
    def sync_videos(self, request: Request, pk: str | None = None) -> Response:
        """Synchronise les vidéos 'rendered' avec VideoMetadata.

        il:
        - crée les entrées manquantes
        - génère la miniature par défaut
        - associe/actualise les liens YouTube
        """
        _ = pk, request
        tournament: Tournament = self.get_object()

        videos = get_video_file_names(tournament.get_rendered_path().absolute())
        created_names = []
        for video in videos:
            if not VideoMetadata.objects.filter(
                name=video.name, tournament=tournament
            ).exists():
                teams = TeamLogo.identify_team(str(video.name))
                new_vid = VideoMetadata.objects.create(
                    name=video.absolute().name,
                    tournament=tournament,
                    team1=teams[0],
                    team2=teams[1],
                    tc=random.random(),
                )
                new_vid.generate_miniature(x_offset=0, y_offset=0, zoom=1)
                created_names.append(video)

        # Mets à jour les liens YT vers les VideoMetadata du tournoi
        YTVideo.objects.update_linked_video(tournament)

        # Retourne l'état courant
        vids_qs = VideoMetadata.objects.filter(tournament=tournament).order_by("name")
        vids_ser = VideoMetadataSerializer(
            vids_qs, many=True, context=self.get_serializer_context()
        )
        return Response(
            {
                "created": created_names,
                "videos": vids_ser.data,
            }
        )

    @action(detail=True, methods=[HTTPMethod.GET], url_path="videos")
    def videos(self, request: Request, pk: str | None = None) -> Response:
        """Get the videos associated with this tournament."""
        _ = pk, request
        tournament = self.get_object()
        qs = VideoMetadata.objects.filter(tournament=tournament).order_by("name")
        serializer = VideoMetadataSerializer(
            qs, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="youtube-update")
    def youtube_update(self, request: Request, pk: str | None = None) -> Response:
        """Trigger update of YouTube videos for this tournament (titres/infos côté YT)."""
        _ = pk, request
        tournament: Tournament = self.get_object()
        YTVideo.youtube_update(tournament)
        return Response({"status": "ok"})


class GameViewSet(viewsets.ModelViewSet[Game]):
    """Game viewset.

    Actions:
        - cuts[GET]: returns the cuts associated with this game.
    """

    serializer_class = GameSerializer
    queryset = Game.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    @action(detail=True, methods=[HTTPMethod.GET], url_path="cuts")
    def cuts(self, request: Request, pk: str | None = None) -> Response:
        """Get the cuts associated with this game."""
        _ = pk, request
        game = self.get_object()
        qs = Cut.objects.filter(game=game).order_by("name")
        serializer = CutSerializer(qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class TeamViewSet(viewsets.ModelViewSet[Team]):
    """Team viewset."""

    serializer_class = TeamSerializer
    queryset = Team.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]


class CutViewSet(viewsets.ModelViewSet[Cut]):
    """Cut viewset."""

    serializer_class = CutSerializer
    queryset = Cut.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]
