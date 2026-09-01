"""Re-queue the archives that were rendered before the downscale worked.

Every archive built while `ffprobe` was answering twice kept its source
resolution, because an unreadable height is treated as "leave the preset
alone". Those files are two to eight times larger than they need to be. This
finds them and puts them back in the render queue.

Nothing is deleted here. A re-render writes under the name the video model
expects today, which is not the legacy name the old file carries, so the old
file survives as an orphan — the command prints those paths, and removing them
stays a separate, deliberate act once the new renders are verified.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.core.management.base import BaseCommand

from core.models.game import Game
from core.models.render_queue.ffmpeg import RenderQueueItemArchive

if TYPE_CHECKING:
    from argparse import ArgumentParser

    from core.models.video import VideoFile

#: What a downscaled archive costs, as a share of the oversized one. Measured
#: on GoPro 4K60 rushes and recorded on RenderQueueItemArchive.
EXPECTED_SHARE = 0.18


class Command(BaseCommand):
    """Re-queue archives left above the target resolution."""

    help = "Ré-enfile les archives restées au-dessus de 1080p."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Declare the command's options."""
        parser.add_argument(
            "--apply",
            action="store_true",
            help="créer les éléments de file ; sinon simple aperçu",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="ne traiter que les N plus gros",
        )
        parser.add_argument(
            "--preset",
            help="preset de rendu ; par défaut la qualité du fichier existant",
        )
        parser.add_argument(
            "--tournament",
            action="append",
            dest="tournaments",
            help="restreindre à ce tournoi (répétable)",
        )

    def _oversized(
        self, tournaments: list[str] | None
    ) -> list[tuple[Game, VideoFile, Path, int, int]]:
        """Return the archives whose stored file is taller than the target."""
        queryset = Game.objects.select_related("tournament", "archive_video").filter(
            archive_video__isnull=False
        )
        if tournaments:
            queryset = queryset.filter(tournament__name__in=tournaments)

        found = []
        for game in queryset:
            archive = game.archive_video
            if archive is None:
                continue
            for video_file in cast("list[VideoFile]", list(archive.files.all())):
                path = Path(video_file.path or "")
                if not video_file.path or not path.exists():
                    continue
                height = RenderQueueItemArchive._source_video_height(path)  # noqa: SLF001
                if height is None or height <= RenderQueueItemArchive.MAX_SOURCE_HEIGHT:
                    continue
                found.append((game, video_file, path, height, path.stat().st_size))

        found.sort(key=lambda row: -row[-1])
        return found

    def handle(self, *args: Any, **options: Any) -> None:
        """Find the oversized archives and, with --apply, re-queue them."""
        _ = args
        rows = self._oversized(options.get("tournaments"))
        if options.get("limit"):
            rows = rows[: options["limit"]]

        if not rows:
            self.stdout.write("Aucune archive au-dessus de 1080p.")
            return

        total = sum(size for *_, size in rows)
        self.stdout.write(
            f"{len(rows)} archive(s) au-dessus de "
            f"{RenderQueueItemArchive.MAX_SOURCE_HEIGHT}p, "
            f"{total / 1e9:.0f} Go au total\n"
        )

        queued, failed = 0, 0
        for game, video_file, path, height, size in rows:
            line = (
                f"  game {game.pk:5d}  {game.tournament.name[:26]:26s} "
                f"{height:5d}p  {size / 1e9:6.1f} Go  {video_file.quality}"
            )
            if not options.get("apply"):
                self.stdout.write(line)
                continue

            preset = options.get("preset") or video_file.quality
            try:
                item = game.enqueue_archive_render(preset=preset, force=True)
            except Exception as error:
                failed += 1
                self.stdout.write(self.style.ERROR(f"{line}  -> échec : {error}"))
                continue
            queued += 1
            self.stdout.write(f"{line}  -> file #{item.pk} (preset {preset})")
            self.stdout.write(f"        ancien fichier à supprimer ensuite : {path}")

        expected = total * EXPECTED_SHARE
        self.stdout.write(
            f"\nTaille attendue après re-rendu : ~{expected / 1e9:.0f} Go, "
            f"soit ~{(total - expected) / 1e9:.0f} Go récupérés."
        )
        if not options.get("apply"):
            self.stdout.write(
                self.style.WARNING("Aperçu seulement. Relancer avec --apply.")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"{queued} rendu(s) enfilé(s)")
            if not failed
            else self.style.WARNING(f"{queued} enfilé(s), {failed} échec(s)")
        )
        self.stdout.write(
            "Les anciens fichiers ne sont pas supprimés : les nouveaux rendus "
            "portent le nom attendu par le modèle, pas l'ancien. Vérifier les "
            "nouvelles archives, puis supprimer les chemins listés ci-dessus."
        )
