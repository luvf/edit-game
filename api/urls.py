"""Urls for API."""

from rest_framework.routers import DefaultRouter

from api.views import (
    CutViewSet,
    GameViewSet,
    TeamLogoViewSet,
    TeamViewSet,
    TmpImageViewSet,
    TournamentsViewSet,
    VideoMetadataViewSet,
    YTVideoViewSet,
)

# Create your views here.
router = DefaultRouter()
router.register(r"team_logos", TeamLogoViewSet, basename="teamlogo")
router.register(r"video_metadatas", VideoMetadataViewSet, basename="videometadata")
router.register(r"tmp_images", TmpImageViewSet, basename="tmpimage")
router.register(r"yt_videos", YTVideoViewSet, basename="ytvideo")

router.register(r"tournaments", TournamentsViewSet, basename="tournament")
router.register(r"games", GameViewSet, basename="game")
router.register(r"teams", TeamViewSet, basename="team")
router.register(r"cuts", CutViewSet, basename="cut")


urlpatterns = router.urls
