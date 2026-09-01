"""Tests for the Video admin columns that derive a video's owner and kind."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from model_bakery import baker

from core.models.cut import Cut
from core.models.video import Video, VideoFile


@pytest.fixture()
def admin_client(db, client):
    """A client logged in as a superuser."""
    User.objects.create_superuser("root", "root@example.com", "pwd")
    client.login(username="root", password="pwd")
    return client


@pytest.fixture()
def videos(game):
    """One video of every kind, all attached to the same game."""
    proxy = baker.make("core.Video", name="proxy video")
    game.video_proxy = proxy
    archive = baker.make("core.Video", name="archive video")
    game.archive_video = archive
    game.save(update_fields=["video_proxy", "archive_video"])

    rendered = baker.make("core.Video", name="cut video")
    cut = Cut.objects.create(game=game, name="cut1", type_cut="MAN")
    cut.rendered_video = rendered
    cut.save(update_fields=["rendered_video"])

    orphan = baker.make("core.Video", name="orphan video")
    return {
        "proxy": proxy,
        "archive": archive,
        "rendered": rendered,
        "orphan": orphan,
        "cut": cut,
        "game": game,
    }


class TestVideoKind:
    def test_kinds_are_derived_from_the_owner(self, videos):
        assert videos["proxy"].kind == Video.Kind.PROXY
        assert videos["rendered"].kind == Video.Kind.GENERATED_RENDERED
        assert videos["archive"].kind == Video.Kind.ARCHIVE
        assert videos["orphan"].kind == Video.Kind.ORPHAN

    def test_owner_is_the_game_or_the_cut(self, videos):
        assert videos["proxy"].owner == videos["game"]
        assert videos["rendered"].owner == videos["cut"]
        assert videos["archive"].owner == videos["game"]
        assert videos["orphan"].owner is None

    def test_orphan_video_has_no_base_path(self, videos):
        with pytest.raises(ValueError, match="not linked to a game"):
            _ = videos["orphan"].base_path


class TestVideoAdmin:
    def test_changelist_shows_kind_and_owner(self, admin_client, videos):
        response = admin_client.get(reverse("admin:core_video_changelist"))

        content = response.content.decode()
        assert response.status_code == 200
        assert "generated rendered" in content
        assert "orpheline" in content
        assert str(videos["cut"]) in content
        assert str(videos["game"]) in content

    @pytest.mark.parametrize("key", ["proxy", "rendered", "archive", "orphan"], ids=str)
    def test_change_page_renders_for_every_kind(self, admin_client, videos, key):
        url = reverse("admin:core_video_change", args=(videos[key].pk,))

        response = admin_client.get(url)

        assert response.status_code == 200
        assert Video.Kind(videos[key].kind).label in response.content.decode()

    @pytest.mark.parametrize(
        ("kind", "expected_key"),
        [
            (Video.Kind.PROXY, "proxy"),
            (Video.Kind.GENERATED_RENDERED, "rendered"),
            (Video.Kind.ARCHIVE, "archive"),
            (Video.Kind.ORPHAN, "orphan"),
        ],
    )
    def test_kind_filter_selects_the_right_videos(
        self, admin_client, videos, kind, expected_key
    ):
        url = reverse("admin:core_video_changelist")

        response = admin_client.get(url, {"kind": kind.value})

        listed = list(response.context["cl"].result_list)
        assert listed == [videos[expected_key]]


class TestVideoFilesInAdmin:
    def test_change_page_lists_the_video_files(self, admin_client, videos, tmp_path):
        real_file = tmp_path / "proxy.mp4"
        real_file.write_bytes(b"x")
        baker.make(
            "core.VideoFile",
            video=videos["proxy"],
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path=str(real_file),
        )
        url = reverse("admin:core_video_change", args=(videos["proxy"].pk,))

        content = admin_client.get(url).content.decode()

        assert str(real_file) in content
        assert "fichier present" in content.lower()

    def test_changelist_links_to_the_filtered_video_files(self, admin_client, videos):
        baker.make(
            "core.VideoFile",
            video=videos["proxy"],
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path="/nope.mp4",
        )

        content = admin_client.get(
            reverse("admin:core_video_changelist")
        ).content.decode()

        assert f"video__id__exact={videos['proxy'].pk}" in content
        assert "0 / 1 sur le disque" in content

    def test_that_link_actually_filters_the_video_file_admin(
        self, admin_client, videos
    ):
        kept = baker.make(
            "core.VideoFile",
            video=videos["proxy"],
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path="/nope.mp4",
        )
        baker.make(
            "core.VideoFile",
            video=videos["rendered"],
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path="/other.mp4",
        )

        response = admin_client.get(
            reverse("admin:core_videofile_changelist"),
            {"video__id__exact": videos["proxy"].pk},
        )

        assert list(response.context["cl"].result_list) == [kept]


@pytest.fixture()
def orphan_file(videos, tmp_path):
    """A file that really exists, owned by the orphan video."""
    real_file = tmp_path / "kept.mp4"
    real_file.write_bytes(b"0123456789")
    baker.make(
        "core.VideoFile",
        video=videos["orphan"],
        quality=VideoFile.Quality.LOW,
        format=VideoFile.Format.MP4,
        path=str(real_file),
    )
    return real_file


class TestDeleteOrphanVideosAction:
    def _run(self, admin_client, pks, **extra):
        return admin_client.post(
            reverse("admin:core_video_changelist"),
            {
                "action": "delete_orphan_videos",
                "_selected_action": [str(pk) for pk in pks],
                **extra,
            },
            follow=True,
        )

    def test_first_post_only_asks_for_confirmation(self, admin_client, videos):
        orphan = videos["orphan"]
        baker.make(
            "core.VideoFile",
            video=orphan,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path="/does/not/exist.mp4",
        )

        response = self._run(admin_client, [orphan.pk])

        content = response.content.decode()
        assert response.status_code == 200
        assert "Oui, supprimer" in content
        assert "/does/not/exist.mp4" in content
        assert "fichier absent" in content
        assert Video.objects.filter(pk=orphan.pk).exists()

    def test_confirmation_shows_files_that_exist(
        self, admin_client, videos, orphan_file
    ):
        response = self._run(admin_client, [videos["orphan"].pk])

        content = response.content.decode()
        assert str(orphan_file) in content
        assert "sur le disque" in content
        assert "effacer leurs fichiers du disque" in content

    def test_confirmation_lists_the_selection_it_will_skip(self, admin_client, videos):
        pks = [videos["orphan"].pk, videos["proxy"].pk]

        content = self._run(admin_client, pks).content.decode()

        assert "ne sont pas orphelines" in content
        assert str(videos["proxy"]) in content

    def test_confirming_deletes_the_selected_orphans(self, admin_client, videos):
        orphan = videos["orphan"]

        self._run(admin_client, [orphan.pk], confirm="yes")

        assert not Video.objects.filter(pk=orphan.pk).exists()

    def test_leaves_linked_videos_alone(self, admin_client, videos):
        pks = [videos[key].pk for key in ("proxy", "rendered", "archive")]

        response = self._run(admin_client, pks, confirm="yes")

        assert Video.objects.filter(pk__in=pks).count() == 3
        assert "Aucune video orpheline dans la selection" in response.content.decode()

    def test_confirming_holds_back_an_orphan_whose_file_still_exists(
        self, admin_client, videos, orphan_file
    ):
        response = self._run(admin_client, [videos["orphan"].pk], confirm="yes")

        assert Video.objects.filter(pk=videos["orphan"].pk).exists()
        assert orphan_file.exists()
        assert "conservee(s)" in response.content.decode()

    def test_checking_the_box_deletes_the_files_too(
        self, admin_client, videos, orphan_file
    ):
        self._run(
            admin_client,
            [videos["orphan"].pk],
            confirm="yes",
            delete_files="on",
        )

        assert not Video.objects.filter(pk=videos["orphan"].pk).exists()
        assert not orphan_file.exists()


@pytest.fixture()
def mixed_files(videos, tmp_path):
    """Two video files present on disk, two missing."""
    present = []
    missing = []
    for index in (1, 2):
        real_file = tmp_path / f"present{index}.mp4"
        real_file.write_bytes(b"x")
        present.append(
            baker.make(
                "core.VideoFile",
                video=videos["proxy"],
                quality=VideoFile.Quality.LOW,
                format=VideoFile.Format.MP4,
                path=str(real_file),
            )
        )
        missing.append(
            baker.make(
                "core.VideoFile",
                video=videos["rendered"],
                quality=VideoFile.Quality.LOW,
                format=VideoFile.Format.MP4,
                path=str(tmp_path / f"gone{index}.mp4"),
            )
        )
    return {"present": present, "missing": missing}


class TestVideoFileOnDiskFilterAndSort:
    def _changelist(self, admin_client, params):
        response = admin_client.get(reverse("admin:core_videofile_changelist"), params)
        return list(response.context["cl"].result_list)

    def test_filter_keeps_only_files_on_disk(self, admin_client, mixed_files):
        listed = self._changelist(admin_client, {"on_disk": "1"})

        assert sorted(row.pk for row in listed) == sorted(
            row.pk for row in mixed_files["present"]
        )

    def test_filter_keeps_only_missing_files(self, admin_client, mixed_files):
        listed = self._changelist(admin_client, {"on_disk": "0"})

        assert sorted(row.pk for row in listed) == sorted(
            row.pk for row in mixed_files["missing"]
        )

    def test_no_filter_lists_everything(self, admin_client, mixed_files):
        listed = self._changelist(admin_client, {})

        assert len(listed) == 4

    def test_sorting_puts_missing_files_first(self, admin_client, mixed_files):
        column = self._on_disk_column_index(admin_client)

        listed = self._changelist(admin_client, {"o": str(column)})

        assert [row.exists_on_disk for row in listed] == [False, False, True, True]

    def test_sorting_descending_puts_present_files_first(
        self, admin_client, mixed_files
    ):
        column = self._on_disk_column_index(admin_client)

        listed = self._changelist(admin_client, {"o": f"-{column}"})

        assert [row.exists_on_disk for row in listed] == [True, True, False, False]

    def test_no_annotation_when_not_sorting_on_it(self, admin_client, mixed_files):
        listed = self._changelist(admin_client, {})

        assert not hasattr(listed[0], "file_present")

    @staticmethod
    def _on_disk_column_index(admin_client) -> int:
        """Read the column position the changelist itself assigns."""
        response = admin_client.get(reverse("admin:core_videofile_changelist"))
        columns = list(response.context["cl"].list_display)
        return columns.index("file_on_disk")


class TestActionsWithoutSelection:
    """An action submitted with an empty selection runs on the whole list."""

    @pytest.fixture(autouse=True)
    def _readable_files(self, monkeypatch):
        """Make every existing file probe to a known frame rate."""
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 25.0))

    def _post(self, admin_client, url, action, selected=()):
        """Post an action the way the changelist form does."""
        return admin_client.post(
            url,
            {
                "action": action,
                "index": "0",
                "_selected_action": [str(pk) for pk in selected],
            },
            follow=True,
        )

    def test_check_action_covers_the_whole_table(self, admin_client, mixed_files):
        url = reverse("admin:core_videofile_changelist")

        self._post(admin_client, url, "check_files_and_refresh_fps")

        checked = VideoFile.objects.filter(fps__isnull=False)
        assert sorted(row.pk for row in checked) == sorted(
            row.pk for row in mixed_files["present"]
        )

    def test_an_active_filter_still_narrows_the_target(self, admin_client, mixed_files):
        url = reverse("admin:core_videofile_changelist")

        self._post(admin_client, f"{url}?on_disk=0", "check_files_and_refresh_fps")

        # Only the missing files were in scope, and none of them can get an fps.
        assert not VideoFile.objects.filter(fps__isnull=False).exists()

    def test_a_selection_is_still_honoured(self, admin_client, mixed_files):
        target = mixed_files["present"][0]
        url = reverse("admin:core_videofile_changelist")

        self._post(
            admin_client, url, "check_files_and_refresh_fps", selected=[target.pk]
        )

        checked = VideoFile.objects.filter(fps__isnull=False)
        assert [row.pk for row in checked] == [target.pk]

    def test_orphan_deletion_without_selection_asks_about_the_whole_table(
        self, admin_client, videos
    ):
        response = self._post(
            admin_client,
            reverse("admin:core_video_changelist"),
            "delete_orphan_videos",
        )

        content = response.content.decode()
        assert "Oui, supprimer" in content
        assert str(videos["orphan"]) in content
        assert Video.objects.filter(pk=videos["orphan"].pk).exists()
