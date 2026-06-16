"""Urls for API."""

from rest_framework.routers import DefaultRouter

from api.views import (
    CutViewSet,
    GameViewSet,
    RenderQueueItemViewSet,
    TeamViewSet,
    TmpImageViewSet,
    TournamentsViewSet,
    VideoMetadataViewSet,
    VideoViewSet,
    YTVideoViewSet,
)

# Create your views here.
router = DefaultRouter()
router.register(r"video_metadatas", VideoMetadataViewSet, basename="videometadata")
router.register(r"tmp_images", TmpImageViewSet, basename="tmpimage")
router.register(r"yt_videos", YTVideoViewSet, basename="ytvideo")

router.register(r"tournaments", TournamentsViewSet, basename="tournament")
router.register(r"games", GameViewSet, basename="game")
router.register(r"teams", TeamViewSet, basename="team")
router.register(r"cuts", CutViewSet, basename="cut")
router.register(r"render-queue", RenderQueueItemViewSet, basename="renderqueue")

router.register("videos", VideoViewSet, basename="video")

urlpatterns = router.urls
