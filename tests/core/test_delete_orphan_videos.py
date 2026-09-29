"""Tests for the delete_orphan_videos management command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from core.models.cut import Cut
from core.models.video import Video, VideoFile


@pytest.fixture()
def linked_videos(game):
    """One video of each linked kind, none of which may ever be deleted."""
    proxy = baker.make("core.Video", name="proxy video")
    archive = baker.make("core.Video", name="archive video")
    game.video_proxy = proxy
    game.archive_video = archive
    game.save(update_fields=["video_proxy", "archive_video"])

    rendered = baker.make("core.Video", name="cut video")
    cut = Cut.objects.create(game=game, name="cut1", type_cut="MAN")
    cut.rendered_video = rendered
    cut.save(update_fields=["rendered_video"])
    return [proxy, archive, rendered]


@pytest.fixture()
def orphan(db):
    """An orphan video with one VideoFile row pointing nowhere."""
    video = baker.make("core.Video", name="orphan")
    baker.make(
        "core.VideoFile",
        video=video,
        quality=VideoFile.Quality.LOW,
        format=VideoFile.Format.MP4,
        path="/does/not/exist.mp4",
    )
    return video


@pytest.fixture()
def orphan_with_file(db, tmp_path):
    """An orphan video whose file is still on disk."""
    video = baker.make("core.Video", name="orphan with file")
    real_file = tmp_path / "kept.mp4"
    real_file.write_bytes(b"0123456789")
    baker.make(
        "core.VideoFile",
        video=video,
        quality=VideoFile.Quality.LOW,
        format=VideoFile.Format.MP4,
        path=str(real_file),
    )
    return video, real_file


def run(*args: str) -> str:
    """Run the command and return what it printed."""
    out = StringIO()
    call_command("delete_orphan_videos", *args, stdout=out, stderr=out)
    return out.getvalue()


class TestDryRun:
    def test_reports_without_deleting(self, orphan):
        output = run()

        assert "Rien n'a ete supprime" in output
        assert f"#{orphan.pk}" in output
        assert Video.objects.filter(pk=orphan.pk).exists()

    def test_says_when_there_is_nothing_to_do(self, linked_videos):
        assert "Aucune video orpheline" in run()


class TestApply:
    def test_deletes_orphan_and_its_rows(self, orphan):
        run("--apply")

        assert not Video.objects.filter(pk=orphan.pk).exists()
        assert not VideoFile.objects.filter(video_id=orphan.pk).exists()

    def test_never_touches_linked_videos(self, linked_videos, orphan):
        run("--apply")

        assert Video.objects.filter(
            pk__in=[video.pk for video in linked_videos]
        ).count() == len(linked_videos)

    def test_holds_back_videos_whose_files_still_exist(self, orphan_with_file):
        video, real_file = orphan_with_file

        output = run("--apply")

        assert "CONSERVEE(S)" in output
        assert Video.objects.filter(pk=video.pk).exists()
        assert real_file.exists()

    def test_include_with_files_deletes_the_row_but_keeps_the_file(
        self, orphan_with_file
    ):
        video, real_file = orphan_with_file

        run("--apply", "--include-with-files")

        assert not Video.objects.filter(pk=video.pk).exists()
        assert real_file.exists()

    def test_delete_files_removes_the_file_too(self, orphan_with_file):
        video, real_file = orphan_with_file

        run("--apply", "--delete-files")

        assert not Video.objects.filter(pk=video.pk).exists()
        assert not real_file.exists()

    def test_delete_files_without_apply_keeps_everything(self, orphan_with_file):
        video, real_file = orphan_with_file

        run("--delete-files")

        assert Video.objects.filter(pk=video.pk).exists()
        assert real_file.exists()

    def test_reports_a_file_it_cannot_remove(self, orphan_with_file, monkeypatch):
        video, real_file = orphan_with_file
        monkeypatch.setattr(
            "pathlib.Path.unlink",
            lambda self, **kwargs: (_ for _ in ()).throw(OSError("read-only")),
        )

        output = run("--apply", "--delete-files")

        assert "Suppression impossible" in output
        assert not Video.objects.filter(pk=video.pk).exists()
