"""Standalone Django bootstrap.

The pipeline only ever reads the database, but it reads it through the ORM so
it stays in sync with the models. Nothing in the web app imports this package;
the dependency goes one way only.
"""

from __future__ import annotations

import os

_SETTINGS = "edit_game.settings"
_ready = False


def setup_django() -> None:
    """Configure Django once, so the models can be imported.

    Safe to call repeatedly; only the first call does anything.
    """
    global _ready  # noqa: PLW0603
    if _ready:
        return

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", _SETTINGS)
    django.setup()
    _ready = True
