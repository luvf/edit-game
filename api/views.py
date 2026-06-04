"""Api Views."""

import contextlib
import json
import mimetypes
import random
import urllib.parse
from collections.abc import Sequence
from http import HTTPMethod
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Model, Q
from django.http import FileResponse, Http404
from django.urls import resolve
from django.utils.text import slugify
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

from api.pagination import StandardResultsSetPagination
from api.serializers import (
    CutSerializer,
    GameSerializer,
    RenderQueueItemSerializer,
    TeamSerializer,
    TmpImageSerializer,
    TournamentSerializer,
    VideoMetadataSerializer,
    YTVideoSerializer,
)
from core.models import (
    Cut,
    Game,
    Team,
    TmpImage,
    Tournament,
    VideoMetadata,
    YTVideo,
)
from core.models import (
    RenderQueueItemBase as RenderQueueItem,
)
from core.tasks import run_async_task
from core.utils.dataset_utils import get_base_json
from jugger_video_manipulation.build_miniature import get_video_file_names

type PermissionClass = type[BasePermission] | OperandHolder | SingleOperandHolder


def _model_from_url[T: Model](url: str, model_cls: type[T]) -> T:
    path = urllib.parse.urlparse(url).path
    resolved_func, _, resolved_kwargs = resolve(path)
    obj = resolved_func.cls().get_queryset().get(pk=resolved_kwargs["pk"])
    if not isinstance(obj, model_cls):
        raise Http404
    return obj


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
        yt_vid = instance.linked_yt_videos.first()
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
        yt_vid = instance.linked_yt_videos.first()
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
        qs = YTVideo.objects.filter(linked_video=instance).order_by(
            "-publication_date", "-pk"
        )
        serializer = YTVideoSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.PATCH], url_path="set-yt-video")
    def set_yt_video(self, request: Request, pk: str | None = None) -> Response:
        """Link the selected YouTube video to this VideoMetadata."""
        _ = pk
        instance: VideoMetadata = self.get_object()
        yt_video_url = request.data.get("yt_video")

        if yt_video_url in (None, ""):
            YTVideo.objects.filter(linked_video=instance).update(linked_video=None)
            return Response({"yt_video": None})

        yt_video = _model_from_url(str(yt_video_url), YTVideo)

        YTVideo.objects.filter(linked_video=instance).exclude(pk=yt_video.pk).update(
            linked_video=None
        )
        yt_video.linked_video = instance
        yt_video.save(update_fields=["linked_video"])

        serializer = YTVideoSerializer(yt_video, context={"request": request})
        return Response({"yt_video": serializer.data})

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

        reset_metadata = False
        # Met à jour éventuellement le time code si fourni

        with contextlib.suppress(TypeError, ValueError):
            instance.miniature_x_offset = float(
                request.data.get("miniature_x_offset", instance.miniature_x_offset)
            )
            instance.miniature_y_offset = float(
                request.data.get("miniature_y_offset", instance.miniature_y_offset)
            )
            instance.miniature_zoom = float(
                request.data.get("miniature_zoom", instance.miniature_zoom)
            )
            instance.time_code = float(
                request.data.get("time_code", instance.time_code)
            )
        with contextlib.suppress(TypeError, ValueError, Http404):
            new_team = _model_from_url(request.data["team1"], Team)
            if new_team != instance.team1:
                reset_metadata = True
                instance.team1 = new_team
            new_team = _model_from_url(request.data["team2"], Team)
            if new_team != instance.team2:
                reset_metadata = True
                instance.team2 = new_team

        if reset_metadata:
            instance.reset_description()
            instance.reset_vid_name()
        instance.save()
        # Génère la miniature
        instance.generate_miniature()
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
        - rendered[GET]: returns rendered filenames for this tournament.
        - source_files[GET]: returns source filenames from this tournament.
        - youtube_update[POST]: Trigger update of YouTube videos.
    """

    serializer_class = TournamentSerializer
    queryset = Tournament.objects.order_by("-date")
    pagination_class = StandardResultsSetPagination
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    @action(detail=True, methods=[HTTPMethod.GET], url_path="games")
    def games(self, request: Request, pk: str | None = None) -> Response:
        """Get the games associated with this tournament."""
        _ = pk, request
        tournament = self.get_object()
        qs = Game.objects.filter(tournament=tournament).order_by("-pk")
        serializer = GameSerializer(
            qs, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="generate_games")
    def generate_games(self, request: Request, pk: str | None = None) -> Response:
        """génère les games d'un tournois pour l'edition.

        it:
        - creates missing Games
        - generates default edits
        """
        _ = pk, request
        tournament: Tournament = self.get_object()
        _ = tournament.generate_games()

        game_qs = Game.objects.filter(tournament=tournament).order_by("-pk")
        game_ser = GameSerializer(
            game_qs, many=True, context=self.get_serializer_context()
        )
        return Response(
            {
                "games": game_ser.data,
            }
        )

    @action(detail=True, methods=[HTTPMethod.POST], url_path="create-game")
    def create_game(self, request: Request, pk: str | None = None) -> Response:
        """Create a single game from explicit teams and source files."""
        _ = pk
        tournament: Tournament = self.get_object()

        raw_files = request.data.get("files") or []
        if isinstance(raw_files, str):
            try:
                raw_files = json.loads(raw_files)
            except json.JSONDecodeError:
                raw_files = [raw_files]
        if not isinstance(raw_files, list):
            return Response(
                {"status": "failed", "error": "files must be a list."}, status=400
            )

        filenames = [
            Path(str(file_name)).name
            for file_name in raw_files
            if str(file_name).strip()
        ]
        filenames = list(dict.fromkeys(filenames))
        if not filenames:
            return Response(
                {"status": "failed", "error": "files is required."}, status=400
            )
        game_name = str(request.data.get("name"))

        existing_game = Game.objects.filter(
            tournament=tournament, files=filenames
        ).first()
        if existing_game is not None:
            serializer = GameSerializer(
                existing_game, context=self.get_serializer_context()
            )
            return Response(serializer.data)

        slug = slugify(f"{tournament.short_name}-{game_name}-{len(filenames)}")
        if not slug:
            slug = slugify(game_name)

        base_json = json.loads(get_base_json())
        base_json["team1"] = ""
        base_json["team2"] = ""
        base_json["dir"] = tournament.source_dir
        base_json["files"] = filenames
        base_json["filename"] = f"{slug}.json"

        game = Game(
            name=game_name,
            files=filenames,
            tournament=tournament,
            rendered="",
            slug=slug,
        )
        content = ContentFile(json.dumps(base_json, indent=4).encode("utf-8"))
        game.json_file.save(f"{slug}.json", content, save=False)
        game.save()

        serializer = GameSerializer(game, context=self.get_serializer_context())
        return Response(serializer.data, status=201)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="sync_videos")
    def sync_videos(self, request: Request, pk: str | None = None) -> Response:
        """Synchronize videos in  'rendered' dir with VideoMetadata.

        il:
        - creates missing VideoMetadata
        - generates default miniature
        - actualize linked YT video
        """
        _ = pk, request
        tournament: Tournament = self.get_object()

        videos = get_video_file_names(tournament.get_rendered_path().absolute())
        created_names = []
        for video in videos:
            # Creates missing video metadata and default miniature
            if not VideoMetadata.objects.filter(
                name=video.name, tournament=tournament
            ).exists():
                teams = Team.identify_team(str(video.name))
                new_vid = VideoMetadata.objects.create(
                    name=video.absolute().name,
                    tournament=tournament,
                    team1=teams[0],
                    team2=teams[1],
                    time_code=random.random(),
                )
                new_vid.generate_miniature()
                created_names.append(video)

        # Mets à jour les liens YT vers les VideoMetadata du tournoi
        YTVideo.objects.update_linked_video(tournament)

        # Retourne l'état courant
        vids_qs = VideoMetadata.objects.filter(tournament=tournament).order_by(
            "-publication_date", "-pk"
        )
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
        qs = VideoMetadata.objects.filter(tournament=tournament).order_by(
            "-publication_date", "-pk"
        )
        serializer = VideoMetadataSerializer(
            qs, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.GET], url_path="rendered")
    def rendered(self, request: Request, pk: str | None = None) -> Response:
        """List rendered filenames for this tournament."""
        _ = pk, request
        tournament = self.get_object()
        rendered_dir = tournament.get_rendered_path().absolute()
        if not rendered_dir.exists():
            return Response([])
        files = get_video_file_names(rendered_dir)
        names = sorted({file.name for file in files})
        return Response(names)

    @action(detail=True, methods=[HTTPMethod.GET], url_path="source-files")
    def source_files(self, request: Request, pk: str | None = None) -> Response:
        """List source filenames from this tournament rushs directory."""
        _ = pk, request
        tournament = self.get_object()
        rushs_dir = (tournament.source_dir_path / "rushs").absolute()
        if not rushs_dir.exists():
            return Response([])
        files = sorted(
            [
                path
                for path in rushs_dir.iterdir()
                if path.is_file() and path.suffix in (".mp4", ".MP4")
            ],
            key=lambda x: x.stat().st_ctime,
        )
        names = [path.name for path in files]
        return Response(names)

    @action(detail=True, methods=[HTTPMethod.GET], url_path="source-file")
    def source_file(
        self, request: Request, pk: str | None = None
    ) -> FileResponse | Response:
        """Stream one source file from the tournament rushs directory."""
        _ = pk
        tournament = self.get_object()
        filename = str(
            request.query_params.get("filename") or request.data.get("filename") or ""
        ).strip()
        if not filename:
            return Response(
                {"status": "failed", "error": "filename is required."}, status=400
            )

        safe_name = Path(filename).name
        rushs_dir = (tournament.source_dir_path / "rushs").resolve()
        source_path = (rushs_dir / safe_name).resolve()
        try:
            source_path.relative_to(rushs_dir)
        except ValueError:
            return Response(
                {"status": "failed", "error": "Invalid filename."}, status=400
            )
        if not source_path.exists():
            raise Http404

        content_type, _ = mimetypes.guess_type(str(source_path))
        return FileResponse(
            source_path.open("rb"),
            content_type=content_type or "application/octet-stream",
        )

    @action(detail=True, methods=[HTTPMethod.POST], url_path="youtube-update")
    def youtube_update(self, request: Request, pk: str | None = None) -> Response:
        """Trigger update of YouTube videos for this tournament (titres/infos côté YT)."""
        _ = pk, request
        tournament: Tournament = self.get_object()
        YTVideo.youtube_update(tournament)
        return Response({"status": "ok"})

    @action(detail=True, methods=[HTTPMethod.POST], url_path="archive")
    def archive(self, request: Request, pk: str | None = None) -> Response:
        """Move the tournament source directory to the archive drive."""
        _ = pk, request
        tournament: Tournament = self.get_object()
        tournament.archive()
        tournament.drive_dir = str(settings.TOURNAMENTS_ARCHIVE_DIR)
        tournament.save(update_fields=["drive_dir"])
        return Response({"status": "ok", "source_dir": tournament.source_dir})


class GameViewSet(viewsets.ModelViewSet[Game]):
    """Game viewset.

    Actions:
        - cuts[GET]: returns the cuts associated with this game.
    """

    serializer_class = GameSerializer
    queryset = Game.objects.all()
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    def get_object(self) -> Game:
        """Fetch a game and normalize stale proxy metadata before returning it."""
        game = super().get_object()
        game.normalize_source_proxy()
        return game

    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Return a single game with a normalized proxy reference."""
        _ = request
        _ = args
        _ = kwargs
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.GET], url_path="cuts")
    def cuts(self, request: Request, pk: str | None = None) -> Response:
        """Get the cuts associated with this game."""
        _ = pk, request
        game = self.get_object()
        qs = Cut.objects.filter(game=game).order_by("name")
        serializer = CutSerializer(qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="generate_proxy")
    def generate_proxy(self, request: Request, pk: str | None = None) -> Response:
        """Generate the proxy video."""
        _ = pk
        game = self.get_object()
        preset = request.data.get("quality") or "low"
        to_queue_value = request.data.get("to_queue")
        to_queue = (
            str(to_queue_value).strip().lower() in {"1", "true", "yes", "y", "on"}
            if to_queue_value is not None
            else True
        )

        try:
            item = game.generate_proxy(preset=preset, to_queue=to_queue)
        except ValueError as exc:
            return Response({"status": "failed", "error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"status": "failed", "error": str(exc)}, status=500)

        serializer = RenderQueueItemSerializer(
            item, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="create-cut")
    def create_cut(self, request: Request, pk: str | None = None) -> Response:
        """Create a new cut for the game."""
        _ = pk
        game = self.get_object()
        name = request.data.get("name") or "New cut"
        slug = request.data.get("slug") or slugify(name)
        type_cut = request.data.get("type_cut") or "MAN"
        cut = Cut.objects.create(game=game, name=name, slug=slug, type_cut=type_cut)
        default_json = json.dumps({"points": [], "overlays": []})
        filename = f"cut_{cut.pk}_data.json"
        cut.json_file.save(
            filename, ContentFile(default_json.encode("utf-8")), save=True
        )
        serializer = CutSerializer(cut, context=self.get_serializer_context())
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

    @action(detail=True, methods=[HTTPMethod.POST], url_path="render")
    def render(self, request: Request, pk: str | None = None) -> Response:
        """Render the cut immediately or enqueue it."""
        _ = pk
        cut = self.get_object()
        preset = request.data.get("preset") or "medium"
        to_queue_value = request.data.get("to_queue")
        to_queue = (
            str(to_queue_value).strip().lower() in {"1", "true", "yes", "y", "on"}
            if to_queue_value is not None
            else False
        )

        try:
            item = cut.render_to_queue(preset=preset, run_now=not to_queue)
        except Exception as exc:
            return Response({"status": "failed", "error": str(exc)}, status=500)
        serializer = RenderQueueItemSerializer(
            item, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="gen-from-file")
    def gen_from_file(self, request: Request, pk: str | None = None) -> Response:
        """Generate cut JSON payload from an XML file."""
        _ = pk
        cut = self.get_object()
        upload_file = request.FILES.get("upload_file")
        if not upload_file:
            return Response(
                {"status": "failed", "error": "upload_file is required."}, status=400
            )
        if upload_file.name.split(".")[-1] not in ["otio", "json"]:
            return Response(
                {
                    "status": "failed",
                    "error": f"upload filed is '{upload_file.name.split(".")[-1]}' expected 'otio' or 'json'  ",
                },
                status=400,
            )
        try:
            payload = cut.gen_from_file(upload_file.read())
            cut.set_json(payload)
        except ElementTree.ParseError as exc:
            return Response({"status": "failed", "error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"status": "failed", "error": str(exc)}, status=500)

        serializer = CutSerializer(cut, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="gen-from-rendered")
    def gen_from_rendered(self, request: Request, pk: str | None = None) -> Response:
        """Generate cut JSON payload from a rendered video path or filename."""
        _ = pk
        cut = self.get_object()
        raw_path = request.data.get("path") or request.data.get("filename")
        if not raw_path:
            return Response(
                {"status": "failed", "error": "path or filename is required."},
                status=400,
            )

        if not cut.game or not cut.game.tournament:
            return Response(
                {"status": "failed", "error": "Cut has no tournament context."},
                status=400,
            )

        candidate = Path(str(raw_path)).expanduser()
        rendered_dir = cut.game.tournament.get_rendered_path().absolute()
        if request.data.get("filename"):
            candidate = rendered_dir / Path(str(raw_path)).name
        elif not candidate.is_absolute():
            candidate = rendered_dir / candidate
        if not candidate.exists():
            return Response(
                {"status": "failed", "error": f"File not found: {candidate}"},
                status=404,
            )

        try:
            payload = cut.gen_from_rendered_queue(candidate)
        except Exception as exc:
            return Response({"status": "failed", "error": str(exc)}, status=500)
        serializer = RenderQueueItemSerializer(
            payload, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=False, methods=[HTTPMethod.GET], url_path="cut-types")
    def cut_types(self, request: Request) -> Response:
        """Return available cut templates."""
        _ = request
        return Response(
            [{"code": code, "label": label} for code, label in Cut.CUT_TYPES]
        )


class RenderQueueItemViewSet(viewsets.ModelViewSet[RenderQueueItem]):
    """Render queue viewset."""

    serializer_class = RenderQueueItemSerializer
    queryset = RenderQueueItem.objects.select_related(
        "renderqueueitemffmpeg__renderqueueitemcut__cut",
        "renderqueueitemffmpeg__renderqueueitemproxy__game",
        "renderqueueitemgencut__cut",
    ).order_by("created_at")
    permission_classes: Sequence[PermissionClass] = [AllowAny]

    http_method_names = ("get", "head", "options", "post", "delete")

    @action(detail=True, methods=[HTTPMethod.POST], url_path="run")
    def run(self, request: Request, pk: str | None = None) -> Response:
        """Run a queued render job immediately."""
        _ = request, pk
        item = self.get_object()
        try:
            item.run_now()
            run_async_task("core.tasks.process_render_queue")
        except ValueError:
            return Response({"status": "running"}, status=409)
        except Exception as exc:
            return Response({"status": "failed", "error": str(exc)}, status=500)
        serializer = RenderQueueItemSerializer(
            item, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=[HTTPMethod.POST], url_path="reset")
    def reset(self, request: Request, pk: str | None = None) -> Response:
        """Reset a render queue item to pending."""
        _ = request, pk
        item = self.get_object()
        item.reset()
        serializer = RenderQueueItemSerializer(
            item, context=self.get_serializer_context()
        )
        return Response(serializer.data)
