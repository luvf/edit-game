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


class TestGamePicker:
    def test_test_partition_is_excluded_by_default(self, app):
        app.run()

        assert app.sidebar.multiselect[0].value == ["train", "val"]

    def test_the_partition_filter_explains_itself(self, app):
        app.run()

        assert "test" in (app.sidebar.multiselect[0].help or "")

    def test_tournaments_carry_their_game_count(self, app):
        app.run()
        options = app.sidebar.selectbox[1].options

        assert options[0].startswith("tous (")
        assert all(option.endswith(")") for option in options)

    def test_a_caption_says_how_many_games_are_shown(self, app):
        app.run()

        assert any("game(s) sur" in caption.value for caption in app.sidebar.caption)

    def test_showing_every_partition_lists_the_whole_catalog(self, app):
        app.run()
        shown = len(app.sidebar.selectbox[2].options)
        app.sidebar.multiselect[0].set_value(["train", "val", "test"]).run()

        assert len(app.sidebar.selectbox[2].options) > shown

    def test_filtering_by_tournament_narrows_the_list(self, app):
        app.run()
        before = len(app.sidebar.selectbox[2].options)
        app.sidebar.selectbox[1].set_value(app.sidebar.selectbox[1].options[1]).run()

        assert len(app.sidebar.selectbox[2].options) < before

    def test_a_button_clears_the_caches(self, app):
        app.run()

        assert any(
            button.label == "Recharger les données" for button in app.sidebar.button
        )


class TestStreamlitConfig:
    """Django cannot re-import a model, so Streamlit must not watch its app."""

    @pytest.fixture()
    def config(self):
        import tomllib

        path = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"
        assert path.exists(), "il faut un .streamlit/config.toml"
        return tomllib.loads(path.read_text())

    def test_django_app_is_not_watched(self, config):
        blacklist = config["server"]["folderWatchBlacklist"]

        assert {"core", "api", "edit_game"} <= set(blacklist)

    def test_the_pipeline_itself_stays_watched(self, config):
        # Hot reload is worth keeping where the iteration happens.
        assert "game_autoedit" not in config["server"]["folderWatchBlacklist"]

    def test_modules_are_not_invalidated_between_runs(self, config):
        assert config["runner"]["fastReruns"] is False
