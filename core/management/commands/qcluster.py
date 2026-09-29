"""Compatibility shim for the legacy django-q qcluster command."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from core.tasks import process_render_queue


class Command(BaseCommand):
    """Django command to run the render queue worker loop."""

    help = "Run the render queue worker loop."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add CLI arguments for the worker loop.

        Args:
            parser: Django argument parser
        """
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help="Seconds to wait between queue polls.",
        )

    def handle(self, *_: object, **options: object) -> None:
        """Run the render queue worker loop.

        Args:
            *args: unused positional args
            **options: command options
        """
        sleep_value = cast(Any, options).get("sleep", 1.0)
        sleep_seconds = float(sleep_value)
        self.stdout.write(self.style.SUCCESS("Starting render queue worker."))
        try:
            while True:
                process_render_queue()
                time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Worker stopped."))
