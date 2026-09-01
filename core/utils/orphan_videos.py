"""Find and delete videos no game and no cut point at.

Shared by the admin action and the ``delete_orphan_videos`` command so both
answer with the same numbers and hold back the same rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from django.db import transaction

from core.models.video import Video

if TYPE_CHECKING:
    from collections.abc import Iterable

    from core.models.video import VideoFile, VideoQuerySet


@dataclass
class OrphanReport:
    """What deleting one orphan video would take away."""

    video: Video
    rows: list[VideoFile]
    files_on_disk: list[Path] = field(default_factory=list)

    @property
    def bytes_on_disk(self) -> int:
        """Return the total size of the files still on disk."""
        return sum(path.stat().st_size for path in self.files_on_disk)

    def line(self) -> str:
        """Return a one-line summary."""
        disk = (
            f", {len(self.files_on_disk)} fichier(s) sur le disque "
            f"({self.bytes_on_disk / 1e9:.2f} Go)"
            if self.files_on_disk
            else ""
        )
        return (
            f"#{self.video.pk} {self.video} "
            f"[{self.video.created_at:%Y-%m-%d}] "
            f"{len(self.rows)} ligne(s) VideoFile{disk}"
        )


def collect(queryset: VideoQuerySet | None = None) -> list[OrphanReport]:
    """Build a report for every orphan video, optionally within a queryset."""
    base = Video.objects.all() if queryset is None else queryset
    orphans = base.orphans().prefetch_related("files").order_by("pk")
    return [
        OrphanReport(
            video=video,
            rows=list(video.files.all()),
            files_on_disk=[
                Path(row.path)
                for row in video.files.all()
                if row.path and Path(row.path).exists()
            ],
        )
        for video in orphans
    ]


def split(reports: Iterable[OrphanReport]) -> tuple[list[OrphanReport], ...]:
    """Split reports into those with no file left and those still holding one."""
    reports = list(reports)
    return (
        [report for report in reports if not report.files_on_disk],
        [report for report in reports if report.files_on_disk],
    )


def delete(
    reports: Iterable[OrphanReport], *, delete_files: bool = False
) -> tuple[int, list[str]]:
    """Delete the given videos, and their files when asked to.

    Returns the number of files removed from disk and the errors met while
    removing them: a file that cannot be unlinked must not abort the run.
    """
    removed = 0
    errors: list[str] = []
    with transaction.atomic():
        for report in reports:
            if delete_files:
                for path in report.files_on_disk:
                    try:
                        path.unlink()
                    except OSError as error:
                        errors.append(f"Suppression impossible de {path} : {error}")
                        continue
                    removed += 1
            report.video.delete()
    return removed, errors
