"""Tests for core.tasks.process_render_queue and the worker file lock."""

from __future__ import annotations

import pytest
from model_bakery import baker

import core.tasks as tasks_module
from core.models.render_queue.base import RenderQueueItemBase
from core.models.render_queue.ffmpeg import RenderQueueItemProxy
from core.tasks import _acquire_render_queue_lock, process_render_queue

Status = RenderQueueItemBase.Status


@pytest.fixture(autouse=True)
def _isolated_lock_file(monkeypatch, tmp_path):
    """Use a per-test lock file instead of the real /tmp/render-queue-worker.lock.

    The real path is shared with any actual qcluster worker that might be
    running on this machine, which would make these tests fail to acquire
    the lock (or spuriously pass) depending on what else is running.
    """
    monkeypatch.setattr(
        tasks_module, "RENDER_QUEUE_LOCK_FILE", str(tmp_path / "render-queue.lock")
    )


class TestAcquireRenderQueueLock:
    def test_second_acquire_fails_while_first_is_held(self):
        lock1 = _acquire_render_queue_lock()
        try:
            assert lock1 is not None
            lock2 = _acquire_render_queue_lock()
            assert lock2 is None
        finally:
            lock1.close()

    def test_lock_can_be_reacquired_after_release(self):
        lock1 = _acquire_render_queue_lock()
        lock1.close()

        lock2 = _acquire_render_queue_lock()
        assert lock2 is not None
        lock2.close()


class TestProcessRenderQueue:
    def test_no_items_does_nothing(self, db):
        process_render_queue()  # should return without raising

    def test_skips_everything_when_another_item_already_running(self, game):
        baker.make("core.RenderQueueItemProxy", game=game, status=Status.RUNNING)
        pending = baker.make(
            "core.RenderQueueItemProxy", game=game, status=Status.CREATED
        )

        process_render_queue()

        pending.refresh_from_db()
        assert pending.status == Status.CREATED

    def test_successful_item_is_marked_done(self, game, monkeypatch):
        monkeypatch.setattr(RenderQueueItemProxy, "_execute", lambda self: None)
        item = baker.make("core.RenderQueueItemProxy", game=game, status=Status.CREATED)

        process_render_queue()

        item.refresh_from_db()
        assert item.status == Status.DONE
        assert item.finished_at is not None

    def test_failing_item_is_marked_failed_with_error(self, game, monkeypatch):
        def _fail(self):
            raise RuntimeError("boom details")

        monkeypatch.setattr(RenderQueueItemProxy, "_execute", _fail)
        item = baker.make("core.RenderQueueItemProxy", game=game, status=Status.CREATED)

        process_render_queue()

        item.refresh_from_db()
        assert item.status == Status.FAILED
        assert "boom details" in item.error

    def test_waiting_item_is_processed_before_older_created_item(
        self, game, monkeypatch
    ):
        order = []
        monkeypatch.setattr(
            RenderQueueItemProxy, "_execute", lambda self: order.append(self.pk)
        )

        older_created = baker.make(
            "core.RenderQueueItemProxy", game=game, status=Status.CREATED
        )
        newer_waiting = baker.make(
            "core.RenderQueueItemProxy", game=game, status=Status.WAITING
        )

        process_render_queue()

        assert order == [newer_waiting.pk, older_created.pk]
