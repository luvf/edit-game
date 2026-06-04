"""Queue tasks for core app."""

from __future__ import annotations

import importlib
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from core.models import RenderQueueItemBase as RenderQueueItem

logger = logging.getLogger(__name__)


def run_async_task(
    task: str | Callable[..., object], *args: object, **kwargs: object
) -> threading.Thread:
    """Run a task in a background thread without external queues."""
    if isinstance(task, str):
        module_path, _, attr_name = task.rpartition(".")
        if not module_path:
            raise ValueError("Task path must be in the form 'module.callable'.")
        module = importlib.import_module(module_path)
        func = getattr(module, attr_name)
    else:
        func = task

    def _runner() -> None:
        try:
            func(*args, **kwargs)
        except Exception:
            logger.exception("Background task failed: %s", task)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


def process_render_queue() -> None:
    """Process render queue items sequentially, enforcing a single RUNNING item."""
    while True:
        # Fast exit if another worker already started a render.
        if RenderQueueItem.objects.filter(
            status=RenderQueueItem.Status.RUNNING
        ).exists():
            return
        item = None
        try:
            with transaction.atomic():
                # Lock one candidate to avoid multiple workers taking the same job.
                item = (
                    RenderQueueItem.objects.select_for_update(skip_locked=True)
                    .filter(
                        status__in=[
                            RenderQueueItem.Status.CREATED,
                            RenderQueueItem.Status.WAITING,
                        ]
                    )
                    .annotate(
                        status_rank=Case(
                            When(status=RenderQueueItem.Status.WAITING, then=Value(0)),
                            default=Value(1),
                            output_field=IntegerField(),
                        )
                    )
                    .order_by("status_rank", "created_at")
                    .first()
                )
                if not item:
                    return
                # Attempt to flip to RUNNING; DB constraint guarantees single RUNNING.
                item.status = RenderQueueItem.Status.RUNNING
                item.started_at = timezone.now()
                item.save(update_fields=["status", "started_at"])
        except IntegrityError:
            # Another worker won the race; put this item back to WAITING and stop.
            if item:
                item.refresh_from_db(fields=["status"])
                if item.status != RenderQueueItem.Status.RUNNING:
                    item.status = RenderQueueItem.Status.WAITING
                    item.started_at = None
                    item.save(update_fields=["status", "started_at"])
            return

        try:
            # Execute render outside the transaction to avoid long-held locks.
            item.concrete().run()
        except Exception as exc:
            updated = RenderQueueItem.objects.filter(
                pk=item.pk, status=RenderQueueItem.Status.RUNNING
            ).update(
                status=RenderQueueItem.Status.FAILED,
                error=str(exc),
                finished_at=timezone.now(),
            )
            if not updated:
                continue
            continue

        updated = RenderQueueItem.objects.filter(
            pk=item.pk, status=RenderQueueItem.Status.RUNNING
        ).update(
            status=RenderQueueItem.Status.DONE,
            finished_at=timezone.now(),
        )
        if not updated:
            continue
