"""Management command to check every video file and repair what it can."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand

from core.models.video import VideoFile

if TYPE_CHECKING:
    from django.core.management.base import CommandParser


class Command(BaseCommand):
    """Check every VideoFile row against the disk.

    For each row: if the stored path leads nowhere, the path is generated
    again from the directory the video resolves to now, and adopted when the
    file turns up there. The frame rate is then re-probed and stored.

    A stale path is what an archived tournament or a renamed video leaves
    behind, so this is worth a run after either.
    """

    help = (
        "Check every video file: repair a stale path, refresh the frame rate. "
        "Each file is probed with ffprobe, so this can be slow on remote storage."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the dry-run flag."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Check the video files and report what each one turned out to be."""
        _ = args
        dry_run = options["dry_run"]
        outcomes: Counter[str] = Counter()

        for video_file in VideoFile.objects.select_related("video").order_by("pk"):
            stale = video_file.path
            outcome, fps = video_file.check_file(save=not dry_run)
            outcomes[outcome] += 1
            self._report(video_file, outcome, fps, stale)

        prefix = "Aurait mis a jour" if dry_run else "Mis a jour"
        summary = ", ".join(
            f"{count} {VideoFile.FileCheck(outcome).label}"
            for outcome, count in sorted(outcomes.items())
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {sum(outcomes.values())} fichier(s) : {summary}"
            )
        )

    def _report(
        self,
        video_file: VideoFile,
        outcome: str,
        fps: float | None,
        stale: str,
    ) -> None:
        """Print one line per row that is not simply fine."""
        if outcome == VideoFile.FileCheck.OK:
            return

        label = VideoFile.FileCheck(outcome).label
        line = f"{video_file.pk} {video_file} : {label}"
        if outcome == VideoFile.FileCheck.PATH_FIXED:
            line += f"\n    avant {stale}\n    apres {video_file.path}"
        elif fps is not None:
            line += f" -> {fps:.6g} fps"
        else:
            line += f" ({video_file.path or '-'})"
        self.stdout.write(line)
