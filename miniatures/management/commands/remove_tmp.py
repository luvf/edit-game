"""Remove tmp images."""

import datetime

from django.core.management.base import BaseCommand

from miniatures.models import TmpImage


class Command(BaseCommand):
    """Remove tmp images."""

    help = "removes image"

    def handle(self) -> None:
        """Handle command."""
        old_images = TmpImage.objects.filter(
            date__range=["2011-01-01", datetime.datetime.now(tz=datetime.UTC).date()]
        )
        for im in old_images:
            im.delete()
