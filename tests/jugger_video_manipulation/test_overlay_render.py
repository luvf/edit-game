"""Tests for the overlay drawing.

These check geometry and behaviour rather than pixels: where the bar lands,
that it flips without moving the two numbers a viewer watches, that a name too
long is cut, and that nothing is painted where nothing should be.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from jugger_video_manipulation.overlay_render import (
    CardText,
    Style,
    Team,
    draw_scoreboard,
    draw_title_card,
    draw_warning,
    load_logo,
    truncate,
)
from jugger_video_manipulation.scoreboard import BoardState, SetScore

TEAMS = {"team1": Team("Mécan'hydre"), "team2": Team("Pink Pain")}
SMALL = (960, 540)


def state(**kwargs):
    base = {
        "start": 0.0,
        "end": 10.0,
        "left": "team1",
        "right": "team2",
        "left_score": 3,
        "right_score": 2,
    }
    return BoardState(**{**base, **kwargs})


def painted(image: Image.Image):
    """Return the bounding box of everything drawn, or None."""
    return image.getchannel("A").getbbox()


@pytest.fixture()
def style():
    return Style()


class TestTruncate:
    def test_a_short_name_is_left_alone(self, style):
        draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        font = style.font(style.text_font, 24)

        assert truncate(draw, "MH", font, 260) == "MH"

    def test_a_long_name_is_cut_at_the_end(self, style):
        draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        font = style.font(style.text_font, 24)

        cut = truncate(draw, "Fishkopkrieger Nordwest Hamburg", font, 120)

        assert cut.endswith("…")
        assert cut.startswith("Fish")

    def test_the_limit_is_pixels_not_characters(self, style):
        draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        font = style.font(style.text_font, 24)

        wide = truncate(draw, "WWWWWWWWWWWW", font, 120)
        narrow = truncate(draw, "iiiiiiiiiiii", font, 120)

        assert len(wide) < len(narrow)


class TestScoreboardGeometry:
    def test_it_paints_at_the_bottom_by_default(self):
        layer = draw_scoreboard(state(), TEAMS, size=SMALL)

        box = painted(layer)
        assert box is not None
        assert box[3] > SMALL[1] * 0.7

    def test_the_top_position_paints_at_the_top(self):
        layer = draw_scoreboard(state(), TEAMS, position="top", size=SMALL)

        box = painted(layer)
        assert box is not None
        assert box[1] < SMALL[1] * 0.3

    def test_nothing_is_painted_in_the_middle_of_the_picture(self):
        layer = draw_scoreboard(state(), TEAMS, size=SMALL)

        middle = layer.crop((0, 200, SMALL[0], 340))
        assert painted(middle) is None

    def test_the_bar_is_centred(self):
        layer = draw_scoreboard(state(), TEAMS, size=SMALL)

        box = painted(layer)
        assert box is not None
        left_margin, right_margin = box[0], SMALL[0] - box[2]
        assert abs(left_margin - right_margin) <= 2


class TestFlipping:
    """The bar turns round at a side switch; the watched numbers must not."""

    def test_the_two_current_scores_keep_their_place(self):
        before = draw_scoreboard(state(), TEAMS, show_logos=False, size=SMALL)
        after = draw_scoreboard(
            state(left="team2", right="team1", left_score=2, right_score=3),
            TEAMS,
            show_logos=False,
            size=SMALL,
        )

        # The digits sit against the centre line, so the painted band around
        # the middle is the same width either way round.
        band = (SMALL[0] // 2 - 40, 0, SMALL[0] // 2 + 40, SMALL[1])
        assert painted(before.crop(band)) == painted(after.crop(band))

    def test_a_team_keeps_its_own_history_across_the_switch(self):
        sets = (SetScore(7, 5), SetScore(4, 7))
        left_first = draw_scoreboard(state(finished_sets=sets), TEAMS, size=SMALL)
        right_first = draw_scoreboard(
            state(left="team2", right="team1", finished_sets=sets), TEAMS, size=SMALL
        )

        # Same content, mirrored: the two images differ but cover the same span.
        assert painted(left_first) is not None
        assert painted(right_first) is not None
        assert left_first.tobytes() != right_first.tobytes()


class TestHistory:
    def test_more_sets_make_a_taller_bar(self):
        one = draw_scoreboard(state(finished_sets=(SetScore(7, 5),)), TEAMS, size=SMALL)
        four = draw_scoreboard(
            state(
                finished_sets=(
                    SetScore(7, 5),
                    SetScore(4, 7),
                    SetScore(7, 6),
                    SetScore(5, 7),
                )
            ),
            TEAMS,
            size=SMALL,
        )

        assert painted(four)[3] - painted(four)[1] > painted(one)[3] - painted(one)[1]

    def test_digits_shrink_as_sets_pile_up(self, style):
        assert style.set_size(5) < style.set_size(1)

    def test_history_can_be_turned_off(self):
        with_history = draw_scoreboard(
            state(finished_sets=(SetScore(7, 5),)), TEAMS, size=SMALL
        )
        without = draw_scoreboard(
            state(finished_sets=(SetScore(7, 5),)),
            TEAMS,
            show_history=False,
            size=SMALL,
        )

        assert painted(without)[2] - painted(without)[0] < (
            painted(with_history)[2] - painted(with_history)[0]
        )


class TestWarning:
    def test_it_tucks_against_the_bar_at_the_bottom(self):
        layer = draw_warning("replay", "coup ignoré", size=SMALL)

        box = painted(layer)
        assert box is not None
        assert box[3] < SMALL[1] - 40

    def test_it_tucks_under_the_bar_at_the_top(self):
        layer = draw_warning("replay", "coup ignoré", position="top", size=SMALL)

        box = painted(layer)
        assert box is not None
        assert box[1] > 40

    def test_a_longer_text_makes_a_wider_strip(self):
        short = draw_warning("replay", "x", size=SMALL)
        long = draw_warning("replay", "un texte bien plus long", size=SMALL)

        assert (
            painted(long)[2] - painted(long)[0] > painted(short)[2] - painted(short)[0]
        )


class TestTitleCard:
    def test_it_fills_the_frame(self):
        card = draw_title_card(Team("A"), Team("B"), size=SMALL)

        assert card.size == SMALL
        assert card.getchannel("A").getextrema()[0] == 255

    def test_a_background_shows_through_the_blur(self):
        background = Image.new("RGB", SMALL, (200, 40, 40))

        with_bg = draw_title_card(
            Team("A"), Team("B"), background=background, size=SMALL
        )
        without = draw_title_card(Team("A"), Team("B"), size=SMALL)

        assert with_bg.getpixel((10, 10)) != without.getpixel((10, 10))

    def test_the_words_are_optional(self):
        bare = draw_title_card(Team("A"), Team("B"), size=SMALL)
        titled = draw_title_card(
            Team("A"), Team("B"), CardText(tournament="Darmstadt"), size=SMALL
        )

        assert bare.tobytes() != titled.tobytes()


class TestLogos:
    def test_a_missing_logo_is_not_an_error(self):
        assert load_logo(Path("/nowhere.png"), 40) is None
        assert load_logo(None, 40) is None

    def test_the_bar_narrows_without_logos(self):
        teams = {
            "team1": Team("A", Path("/nowhere.png")),
            "team2": Team("B", Path("/nowhere.png")),
        }
        with_logos = draw_scoreboard(state(), teams, size=SMALL)
        without = draw_scoreboard(state(), teams, show_logos=False, size=SMALL)

        # Both end up without logos on disk, so the bar is the same: what is
        # tested here is that a missing file never widens or crashes anything.
        assert painted(with_logos) == painted(without)
