"""The dashboard must render, on the real cache, without raising.

These are integration tests: they read the developer's database and cache
rather than fixtures, because what they guard against is a page that breaks on
real data. They skip themselves when that data is not on the machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from game_autoedit import dashboard
from game_autoedit.config import Paths

APP = str(Path(dashboard.__file__).parent / "app.py")
SCREENS = ("Game", "Runs", "Dataset")


def _has_data() -> bool:
    """Tell whether this machine holds a database and at least one run."""
    from django.conf import settings

    from game_autoedit.bootstrap import setup_django

    setup_django()
    database = Path(settings.DATABASES["default"]["NAME"])
    runs = Paths().runs
    return database.exists() and any(runs.glob("*/best.pt"))


pytestmark = pytest.mark.skipif(
    not _has_data(), reason="base ou cache d'entraînement absents de cette machine"
)


@pytest.fixture()
def app(django_db_blocker):
    """Return an app runner allowed to read the real, unmanaged database."""
    from streamlit.testing.v1 import AppTest

    with django_db_blocker.unblock():
        yield AppTest.from_file(APP, default_timeout=600)


class TestDashboard:
    def test_starts_on_the_game_screen(self, app):
        app.run()

        assert not app.exception
        assert app.title[0].value == "Game"

    def test_offers_every_screen(self, app):
        app.run()

        assert tuple(app.sidebar.radio[0].options) == SCREENS

    @pytest.mark.parametrize("screen", SCREENS)
    def test_screen_renders_without_raising(self, app, screen):
        app.run()
        app.sidebar.radio[0].set_value(screen).run()

        assert not app.exception, [str(error.value) for error in app.exception]
        assert app.title[0].value == screen
