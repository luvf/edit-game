"""Tests for core.models.media (TmpImage, VideoMetadata, YTVideo).

External I/O is always mocked: `get_chapters`/`get_frame` (ffmpeg/moviepy),
`generate_miniature` (PIL composition), and `YTInteraction` (YouTube OAuth +
network) are never exercised for real here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from model_bakery import baker
from PIL import Image

from core.models.media import TmpImage, VideoMetadata, YTVideo
from core.youtube_interaction.yt_interaction import YtVideoMetadata


class TestTmpImageFromPil:
    def test_saves_image_as_jpeg(self, db):
        img = Image.new("RGB", (10, 10), color="red")
        tmp_image = TmpImage(name="test.jpeg")

        tmp_image.from_pil(img)

        assert tmp_image.image.name
        tmp_image.image.seek(0)
        assert Image.open(tmp_image.image).format == "JPEG"


class TestTmpImageDelete:
    def test_removes_the_underlying_storage_file(self, db):
        img = Image.new("RGB", (10, 10), color="blue")
        tmp_image = TmpImage(name="test2.jpeg")
        tmp_image.from_pil(img)
        tmp_image.save()

        storage = tmp_image.image.storage
        name = tmp_image.image.name
        assert storage.exists(name)

        tmp_image.delete()

        assert not storage.exists(name)


class TestDescription:
    def test_builds_description_with_chapters(self, tournament, monkeypatch):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        tournament.tugeny_link = "http://tugeny"
        tournament.JTR = "JTR info"
        tournament.save()
        monkeypatch.setattr(
            "core.models.media.get_chapters",
            lambda video_file: [(0.0, 1.0), (65.0, 2.0)],
        )

        description = VideoMetadata.objects.description(
            tournament, "match.mp4", team1, team2
        )

        assert description.startswith("Alpha vs Beta")
        assert str(tournament.date) in description
        assert "http://tugeny" in description
        assert "JTR info" in description
        assert "00:00 Point 1" in description
        assert "01:05 Point 2" in description


class TestVideoMetadataManagerCreate:
    def test_computes_derived_fields(self, tournament, monkeypatch):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        monkeypatch.setattr("core.models.media.get_chapters", lambda video_file: [])

        vm = VideoMetadata.objects.create(
            name="match.mp4",
            tournament=tournament,
            team1=team1,
            team2=team2,
            time_code=0.5,
        )

        assert (
            vm.video_name
            == f"match.mp4 vs Alpha vs Beta | {tournament.name.upper()} [JUGGER]"
        )
        assert "Alpha vs Beta" in vm.description
        assert vm.publication_date.hour == 18


class TestResetTeams:
    def test_uses_identify_team(self, tournament):
        team_a = baker.make("core.Team", name="Alpha", short_name="ALP")
        team_b = baker.make("core.Team", name="Beta", short_name="BET")
        vm = VideoMetadata(name="clip_ALP_vs_BET.mp4", tournament=tournament)

        vm.reset_teams()

        assert {vm.team1, vm.team2} == {team_a, team_b}


class TestResetDescriptionAndVidName:
    def test_raise_without_tournament_or_teams(self, tournament):
        vm = VideoMetadata(name="x", tournament=None)
        with pytest.raises(ValueError, match="not set"):
            vm.reset_description()
        with pytest.raises(ValueError, match="not set"):
            vm.reset_vid_name()

    def test_reset_description_builds_from_chapters(self, tournament, monkeypatch):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        monkeypatch.setattr("core.models.media.get_chapters", lambda video_file: [])
        vm = VideoMetadata(
            name="match.mp4", tournament=tournament, team1=team1, team2=team2
        )

        vm.reset_description()

        assert "Alpha vs Beta" in vm.description

    def test_reset_vid_name(self, tournament):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        vm = VideoMetadata(
            name="match.mp4", tournament=tournament, team1=team1, team2=team2
        )

        vm.reset_vid_name()

        assert vm.video_name == f"Alpha vs Beta | {tournament.name.upper()} [JUGGER]"


class TestMakeMetadata:
    def test_raises_without_teams(self, tournament):
        vm = VideoMetadata(name="x", tournament=tournament)
        with pytest.raises(ValueError, match="Teams are not set"):
            vm.make_metadata()

    def test_builds_context(self, tournament):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        vm = VideoMetadata(
            name="x",
            tournament=tournament,
            team1=team1,
            team2=team2,
            description="desc text",
            publication_date=datetime(2024, 1, 2, 15, 30, tzinfo=UTC),
        )

        context = vm.make_metadata()

        assert (
            context["vid_name"] == f"Alpha vs Beta | {tournament.name.upper()} [JUGGER]"
        )
        assert context["description"] == "desc text"
        assert context["pub_date"] == "2024-01-02T15:30"


class TestVideoMetadataDelete:
    def test_deletes_miniature_image_storage_file(self, tournament):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        img = Image.new("RGB", (5, 5))
        miniature = TmpImage(name="mini.jpeg")
        miniature.from_pil(img)
        miniature.save()

        vm = VideoMetadata(
            name="x",
            tournament=tournament,
            team1=team1,
            team2=team2,
            miniature_image=miniature,
        )
        vm.save()

        storage = miniature.image.storage
        file_name = miniature.image.name

        vm.delete()

        assert not storage.exists(file_name)


class TestGenerateMiniature:
    def test_raises_without_tournament(self, db):
        vm = VideoMetadata(name="match.mp4")
        with pytest.raises(ValueError, match="Tournament is not set"):
            vm.generate_miniature()

    def test_raises_without_teams(self, tournament, monkeypatch):
        monkeypatch.setattr(
            "core.models.media.get_frame", lambda path, tc: Image.new("RGB", (5, 5))
        )
        vm = VideoMetadata(name="match.mp4", tournament=tournament, time_code=0.1)

        with pytest.raises(ValueError, match="Teams are not set"):
            vm.generate_miniature()

    def test_generates_and_persists_base_and_miniature_images(
        self, tournament, monkeypatch
    ):
        team1 = baker.make("core.Team", name="Alpha")
        team2 = baker.make("core.Team", name="Beta")
        frame_img = Image.new("RGB", (20, 10), color="green")
        thumb_img = Image.new("RGB", (20, 10), color="yellow")

        monkeypatch.setattr("core.models.media.get_frame", lambda path, tc: frame_img)
        monkeypatch.setattr(
            "core.models.media.generate_miniature", lambda **kwargs: thumb_img
        )

        vm = VideoMetadata(
            name="match.mp4",
            tournament=tournament,
            team1=team1,
            team2=team2,
            time_code=0.25,
        )

        vm.generate_miniature()

        assert vm.pk is not None
        assert vm.base_image is not None
        assert vm.miniature_image is not None


class TestUpdateLinkedVideo:
    def test_links_video_by_matching_title(self, tournament):
        team1 = baker.make("core.Team")
        team2 = baker.make("core.Team")
        vm = VideoMetadata(
            name="Finale",
            tournament=tournament,
            team1=team1,
            team2=team2,
            video_name="Finale video",
        )
        vm.save()
        yt = baker.make("core.YTVideo", title="Finale", video_id="abc123")

        YTVideo.objects.update_linked_video()

        yt.refresh_from_db()
        assert yt.linked_video == vm

    def test_scopes_to_tournament_when_given(self, tournament):
        other_tournament = baker.make(
            "core.Tournament", drive_dir="/tmp/other", tournament_dir="other"
        )
        team1 = baker.make("core.Team")
        team2 = baker.make("core.Team")
        vm_other = VideoMetadata(
            name="Finale", tournament=other_tournament, team1=team1, team2=team2
        )
        vm_other.save()
        yt = baker.make("core.YTVideo", title="Finale", video_id="xyz789")

        YTVideo.objects.update_linked_video(tournament=tournament)

        yt.refresh_from_db()
        assert yt.linked_video is None


class TestYTVideoUpdate:
    def test_updates_fields_from_dict(self, tournament):
        team1 = baker.make("core.Team")
        team2 = baker.make("core.Team")
        vm = VideoMetadata(name="x", tournament=tournament, team1=team1, team2=team2)
        vm.save()
        yt = YTVideo(video_id="v1", linked_video=vm)

        yt.update(
            {
                "title": "New title",
                "videoid": "v2",
                "description": "new desc",
                "date": datetime(2024, 1, 1, tzinfo=UTC),
                "privacystatus": "public",
            }
        )

        assert yt.title == "New title"
        assert yt.video_id == "v2"
        assert yt.linked_video.description == "new desc"
        assert yt.publication_date == datetime(2024, 1, 1, tzinfo=UTC)
        assert yt.privacy_status == "public"


class TestUploadDescription:
    def test_noop_without_linked_video(self, db):
        yt = YTVideo(video_id="v1", linked_video=None)
        yt.upload_description()  # should not raise

    def test_updates_from_yt_interaction_response(self, tournament, monkeypatch):
        team1 = baker.make("core.Team")
        team2 = baker.make("core.Team")
        vm = VideoMetadata(name="x", tournament=tournament, team1=team1, team2=team2)
        vm.save()
        yt = baker.make("core.YTVideo", video_id="v1", linked_video=vm)

        class FakeInteraction:
            def update_video(self, body):
                _ = body
                return YtVideoMetadata(
                    video_id="v1",
                    title="Updated",
                    description="d",
                    date=datetime(2024, 1, 1, tzinfo=UTC),
                    status="public",
                )

        monkeypatch.setattr("core.models.media.YTInteraction", FakeInteraction)

        yt.upload_description()

        yt.refresh_from_db()
        assert yt.title == "Updated"
        assert yt.privacy_status == "public"


class TestUploadMiniature:
    def test_noop_without_linked_video(self, db):
        yt = YTVideo(video_id="v1")
        yt.upload_miniature()  # should not raise

    def test_calls_set_miniature_with_image_path(self, tournament, monkeypatch):
        team1 = baker.make("core.Team")
        team2 = baker.make("core.Team")
        img = Image.new("RGB", (5, 5))
        miniature = TmpImage(name="mini.jpeg")
        miniature.from_pil(img)
        miniature.save()
        vm = VideoMetadata(
            name="x",
            tournament=tournament,
            team1=team1,
            team2=team2,
            miniature_image=miniature,
        )
        vm.save()
        yt = baker.make("core.YTVideo", video_id="v1", linked_video=vm)

        calls = []

        class FakeInteraction:
            def set_miniature(self, video_id, image_file):
                calls.append((video_id, image_file))

        monkeypatch.setattr("core.models.media.YTInteraction", FakeInteraction)

        yt.upload_miniature()

        assert calls == [("v1", miniature.path)]


class TestYoutubeUpdate:
    def test_creates_new_ytvideo_entries(self, tournament, monkeypatch):
        class FakeInteraction:
            def get_all_videos(self):
                return [
                    YtVideoMetadata(
                        video_id="vid1",
                        title="T1",
                        description="",
                        date=datetime(2024, 1, 1, tzinfo=UTC),
                        status="public",
                    )
                ]

        monkeypatch.setattr("core.models.media.YTInteraction", FakeInteraction)

        YTVideo.youtube_update(tournament)

        assert YTVideo.objects.filter(video_id="vid1", title="T1").exists()

    def test_sync_local_videos_links_matching_metadata(self, tournament, monkeypatch):
        team1 = baker.make("core.Team")
        team2 = baker.make("core.Team")
        vm = VideoMetadata(
            name="Match1", tournament=tournament, team1=team1, team2=team2
        )
        vm.save()

        class FakeInteraction:
            def get_all_videos(self):
                return [
                    YtVideoMetadata(
                        video_id="vid1",
                        title="Match1",
                        description="",
                        date=datetime(2024, 1, 1, tzinfo=UTC),
                        status="public",
                    )
                ]

        monkeypatch.setattr("core.models.media.YTInteraction", FakeInteraction)

        YTVideo.youtube_update(tournament, sync_local_videos=True)

        yt = YTVideo.objects.get(video_id="vid1")
        assert yt.linked_video == vm
