"""Management command to fill the fps field of existing video files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand

from core.models.video import VideoFile

if TYPE_CHECKING:
    from django.core.management.base import CommandParser


class Command(BaseCommand):
    """Probe existing video files with ffprobe and store their frame rate."""

    help = (
        "Fill VideoFile.fps for files rendered before the field existed. "
        "Each file is probed with ffprobe, so this can be slow on remote storage."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add command-line arguments for scoping and dry runs."""
        parser.add_argument(
            "--all",
            action="store_true",
            dest="probe_all",
            help="Re-probe every file, including those that already have an fps.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would be written without saving.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Probe the selected video files and persist their frame rate."""
        _ = args
        video_files = VideoFile.objects.all().order_by("pk")
        if not options["probe_all"]:
            video_files = video_files.filter(fps__isnull=True)

        updated = 0
        missing = 0
        failed = 0

        for video_file in video_files.iterator():
            if not video_file.path:
                missing += 1
                continue

            path = Path(video_file.path)
            if not path.exists():
                missing += 1
                continue

            fps = VideoFile.probe_fps(path)
            if fps is None:
                failed += 1
                self.stderr.write(f"ffprobe failed on {path}")
                continue

            if not options["dry_run"]:
                video_file.fps = fps
                video_file.save(update_fields=["fps"])
            updated += 1
            self.stdout.write(f"{video_file.pk} {path.name} -> {fps:.6g}")

        prefix = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {updated} file(s). "
                f"{missing} missing on disk, {failed} probe error(s)."
            )
        )
