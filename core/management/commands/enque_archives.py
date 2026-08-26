"""Management command to enqueue archive renders for games."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from core.models.game import Game

if TYPE_CHECKING:
    from django.core.management.base import CommandParser
    from django.db.models import QuerySet


class Command(BaseCommand):
    """Enqueue archive render tasks for games."""

    help = "Create archive render queue items for games, optionally filtered by tournament date."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add command-line arguments for filtering games and specifying render options."""
        parser.add_argument(
            "--from-date",
            dest="from_date",
            help="Only include games whose tournament date is greater than or equal to this date. Format: YYYY-MM-DD.",
        )
        parser.add_argument(
            "--to-date",
            dest="to_date",
            help="Only include games whose tournament date is less than or equal to this date. Format: YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-field",
            dest="date_field",
            default="tournament__date",
            help=(
                "Tournament date field to filter on. "
                "Default: tournament__date. "
                "Example: tournament__start_date or tournament__created_at."
            ),
        )
        parser.add_argument(
            "--preset",
            dest="preset",
            default="high",
            help="Archive render preset. Default: high.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create a new archive render item even if an archive or pending item already exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be enqueued without creating queue items.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        """Enqueue archive render tasks for games, optionally filtered by tournament date."""
        from_date_raw = options["from_date"]
        to_date_raw = options["to_date"]
        date_field = options["date_field"]
        preset = options["preset"]
        force = options["force"]
        dry_run = options["dry_run"]

        games = self.get_games_queryset()

        if from_date_raw:
            from_date = parse_date(from_date_raw)
            if from_date is None:
                self.stderr.write(
                    self.style.ERROR("--from-date must use format YYYY-MM-DD.")
                )
                return
            games = games.filter(**{f"{date_field}__gte": from_date})

        if to_date_raw:
            to_date = parse_date(to_date_raw)
            if to_date is None:
                self.stderr.write(
                    self.style.ERROR("--to-date must use format YYYY-MM-DD.")
                )
                return
            games = games.filter(**{f"{date_field}__lte": to_date})

        total = games.count()
        created = 0
        skipped = 0
        failed = 0

        self.stdout.write(f"Found {total} game(s).")

        for game in games.iterator():
            label = f"Game #{game.pk} - {game.name}"

            if dry_run:
                self.stdout.write(f"[DRY-RUN] Would enqueue archive render for {label}")
                continue

            try:
                item = game.enqueue_archive_render(
                    preset=preset,
                    force=force,
                )
            except ValidationError as exc:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skipped {label}: {exc}"))
                continue
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"Failed {label}: {exc}"))
                continue

            created += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created archive render item #{item.pk} for {label}"
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))
        self.stdout.write(self.style.WARNING(f"Skipped: {skipped}"))

        if failed:
            self.stdout.write(self.style.ERROR(f"Failed: {failed}"))

    def get_games_queryset(self) -> QuerySet[Game]:
        """Return the base games queryset."""
        return Game.objects.select_related(
            "tournament",
            "archive_video",
        ).order_by("tournament_id", "id")
