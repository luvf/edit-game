"""Management command to delete videos no game and no cut point at."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand

from core.utils import orphan_videos

if TYPE_CHECKING:
    from django.core.management.base import CommandParser

    from core.utils.orphan_videos import OrphanReport


class Command(BaseCommand):
    """Delete Video rows nothing points at anymore.

    A video is reachable only through Game.video_proxy, Game.archive_video or
    Cut.rendered_video. A row missing all three is dead weight: no page, no
    render and no API response can reach it. Its VideoFile rows go with it,
    through the cascade.

    Nothing is deleted without --apply, and videos whose files are still on
    disk are held back unless --include-with-files says otherwise: dropping
    those rows would leave the files behind with nothing naming them.
    """

    help = (
        "Delete videos no game and no cut point at. Reports without deleting "
        "unless --apply is given."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the scoping and safety flags."""
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without it the command only reports.",
        )
        parser.add_argument(
            "--include-with-files",
            action="store_true",
            dest="include_with_files",
            help=(
                "Also delete orphans whose files are still on disk. "
                "The files themselves are kept unless --delete-files."
            ),
        )
        parser.add_argument(
            "--delete-files",
            action="store_true",
            dest="delete_files",
            help="Also remove those files from disk. Implies --include-with-files.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Report the orphan videos, then delete them when asked to."""
        _ = args
        delete_files = options["delete_files"]
        include_with_files = options["include_with_files"] or delete_files

        reports = orphan_videos.collect()
        if not reports:
            self.stdout.write(self.style.SUCCESS("Aucune video orpheline."))
            return

        clean, with_files = orphan_videos.split(reports)
        targets = clean + with_files if include_with_files else clean

        self._report(clean, with_files, include_with_files=include_with_files)
        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Rien n'a ete supprime. Relancer avec --apply pour "
                    f"supprimer {len(targets)} video(s)."
                )
            )
            return

        removed, errors = orphan_videos.delete(targets, delete_files=delete_files)
        for error in errors:
            self.stderr.write(error)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(targets)} video(s) supprimee(s), "
                f"{sum(len(report.rows) for report in targets)} ligne(s) VideoFile, "
                f"{removed} fichier(s) efface(s) du disque."
            )
        )

    def _report(
        self,
        clean: list[OrphanReport],
        with_files: list[OrphanReport],
        *,
        include_with_files: bool,
    ) -> None:
        """Print both groups, so the held-back one is never a surprise."""
        self.stdout.write(f"{len(clean)} video(s) orpheline(s) sans fichier :")
        for report in clean:
            self.stdout.write(f"  {report.line()}")

        if not with_files:
            return

        total = sum(report.bytes_on_disk for report in with_files)
        verb = "a supprimer" if include_with_files else "CONSERVEE(S)"
        self.stdout.write("")
        self.stdout.write(
            f"{len(with_files)} video(s) orpheline(s) avec des fichiers encore "
            f"presents ({total / 1e9:.2f} Go), {verb} :"
        )
        for report in with_files:
            self.stdout.write(f"  {report.line()}")
        if not include_with_files:
            self.stdout.write(
                "  -> --include-with-files pour les supprimer aussi, "
                "--delete-files pour effacer les fichiers avec."
            )
