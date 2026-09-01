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
def _real_media(settings):
    """Undo the conftest's media isolation, for these read-only tests.

    The dashboard reads the cut files through MEDIA_ROOT, so with the isolated
    temporary root the catalog comes back empty and every assertion passes
    vacuously. These tests never write, and `settings` restores the override
    afterwards. The original value still sits on the settings module, which the
    fixture patches only through django.conf.
    """
    import edit_game.settings as project_settings

    settings.MEDIA_ROOT = project_settings.MEDIA_ROOT


@pytest.fixture()
def app(django_db_blocker, _real_media):
    """Return an app runner allowed to read the real, unmanaged database.

    Skips when the catalog comes back empty. That happens as soon as any
    `django_db` test has run first: pytest-django then points the default
    connection at the test database for the rest of the session, and these
    tests read the developer's real one. They are worth running — they caught
    a page that raised on empty data — but only on their own:

        uv run pytest tests/game_autoedit/test_dashboard.py
    """
    from streamlit.testing.v1 import AppTest

    from game_autoedit.dashboard import loading

    with django_db_blocker.unblock():
        loading.catalog.clear()
        if not loading.catalog().games:
            pytest.skip("base réelle inaccessible depuis cette session pytest")
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


class TestGameControls:
    def test_every_slider_carries_a_tooltip(self, app):
        app.run()

        missing = [slider.label for slider in app.sidebar.slider if not slider.help]
        assert not missing

    def test_one_toggle_per_curve(self, app):
        app.run()

        assert [toggle.label for toggle in app.toggle] == ["in", "out", "inside"]

    def test_curves_start_shown(self, app):
        app.run()

        assert all(toggle.value for toggle in app.toggle)

    def test_hiding_a_curve_does_not_break_the_page(self, app):
        app.run()
        app.toggle[1].set_value(False).run()

        assert not app.exception, [str(error.value) for error in app.exception]
        assert app.toggle[1].value is False

    def test_hiding_every_curve_still_renders(self, app):
        app.run()
        for index in range(3):
            app.toggle[index].set_value(False)
        app.run()

        assert not app.exception, [str(error.value) for error in app.exception]

    def test_moving_a_threshold_recomputes(self, app):
        app.run()
        before = app.metric[0].value
        app.sidebar.slider[0].set_value(0.95).run()

        assert not app.exception
        assert app.metric[0].value != before or app.metric[1].value is not None
