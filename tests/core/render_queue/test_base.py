"""Tests for core.models.render_queue.base.RenderQueueItemBase."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from model_bakery import baker

from core.models.cut import Cut
from core.models.render_queue.base import RenderQueueItemBase

Status = RenderQueueItemBase.Status


class FakePopenResult:
    """Minimal stand-in for a subprocess.Popen instance."""

    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.pid = 999
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self):
        return self._stdout, self._stderr


class TestSingleRunningConstraint:
    def test_only_one_running_item_allowed(self, game):
        baker.make("core.RenderQueueItemProxy", game=game, status=Status.RUNNING)
        item2 = baker.make(
            "core.RenderQueueItemProxy", game=game, status=Status.CREATED
        )

        item2.status = Status.RUNNING
        with pytest.raises(IntegrityError), transaction.atomic():
            item2.save(update_fields=["status"])


class TestCutGameResolution:
    def test_cut_render_item_resolves_cut_and_game(self, game):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        item = baker.make("core.RenderQueueItemCut", cut=cut)

        base_item = RenderQueueItemBase.objects.get(pk=item.pk)
        assert base_item.cut == cut
        assert base_item.game == game

    def test_proxy_item_resolves_game_only(self, game):
        item = baker.make("core.RenderQueueItemProxy", game=game)

        base_item = RenderQueueItemBase.objects.get(pk=item.pk)
        assert base_item.cut is None
        assert base_item.game == game

    def test_archive_item_resolves_game_only(self, game):
        item = baker.make("core.RenderQueueItemArchive", game=game)

        base_item = RenderQueueItemBase.objects.get(pk=item.pk)
        assert base_item.cut is None
        assert base_item.game == game

    def test_gen_cut_item_resolves_cut_and_game(self, game):
        cut = Cut.objects.create(game=game, name="c2", type_cut="MAN")
        item = baker.make("core.RenderQueueItemGenCut", cut=cut, rendered_path="x")

        base_item = RenderQueueItemBase.objects.get(pk=item.pk)
        assert base_item.cut == cut
        assert base_item.game == game


class TestRunNow:
    def test_transitions_created_to_waiting(self, game):
        item = baker.make("core.RenderQueueItemProxy", game=game, status=Status.CREATED)
        item.run_now()
        assert item.status == Status.WAITING

    def test_raises_when_already_running(self, game):
        item = baker.make("core.RenderQueueItemProxy", game=game, status=Status.RUNNING)
        with pytest.raises(ValueError, match="already running"):
            item.run_now()


class TestReset:
    def test_terminates_pid_and_resets_fields(self, game, monkeypatch):
        killed = []
        monkeypatch.setattr("os.kill", lambda pid, sig: killed.append((pid, sig)))
        monkeypatch.setattr("time.sleep", lambda *_a: None)
        item = baker.make(
            "core.RenderQueueItemProxy",
            game=game,
            status=Status.RUNNING,
            pid=1234,
            error="boom",
        )

        item.reset()

        assert item.status == Status.CREATED
        assert item.pid is None
        assert item.error == ""
        assert item.started_at is None
        assert item.finished_at is None
        assert killed

    def test_noop_when_no_pid(self, game, monkeypatch):
        monkeypatch.setattr(
            "os.kill", lambda *_a: pytest.fail("os.kill should not run")
        )
        item = baker.make(
            "core.RenderQueueItemProxy", game=game, status=Status.RUNNING, pid=None
        )

        item.reset()

        assert item.status == Status.CREATED


class TestRunSubprocess:
    def test_success_clears_pid(self, game, monkeypatch):
        monkeypatch.setattr(
            "subprocess.Popen", lambda *a, **k: FakePopenResult(returncode=0)
        )
        item = baker.make("core.RenderQueueItemProxy", game=game)

        item._run_subprocess(["ffmpeg", "-version"])

        assert item.pid is None

    def test_nonzero_exit_raises_with_stderr(self, game, monkeypatch):
        monkeypatch.setattr(
            "subprocess.Popen",
            lambda *a, **k: FakePopenResult(returncode=1, stderr="boom output"),
        )
        item = baker.make("core.RenderQueueItemProxy", game=game)

        with pytest.raises(RuntimeError, match="boom output"):
            item._run_subprocess(["ffmpeg"])

    def test_spawn_oserror_is_enriched_with_command(self, game, monkeypatch):
        def _raise(*_a, **_k):
            raise OSError(11, "Resource temporarily unavailable")

        monkeypatch.setattr("subprocess.Popen", _raise)
        item = baker.make("core.RenderQueueItemProxy", game=game)

        with pytest.raises(OSError, match="ffmpeg -version"):
            item._run_subprocess(["ffmpeg", "-version"])
