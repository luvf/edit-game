"""Tests for the overlay drawing.

These check geometry and behaviour rather than pixels: where the bar lands,
that it flips without moving the two numbers a viewer watches, that a name too
long is cut, and that nothing is painted where nothing should be.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from jugger_video_manipulation.overlay_render import (
    CardText,
    Style,
    Team,
    draw_scoreboard,
    draw_title_card,
    draw_warning,
    generated_logo,
    load_logo,
    scoreboard_layout,
    team_logo,
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

    def test_the_card_has_no_room_for_an_internal_label(self):
        # The cut's name used to be drawn under the tournament; a viewer has
        # no use for it, so `CardText` no longer has anywhere to put it.
        assert not hasattr(CardText(), "stage")

    def test_a_card_for_the_moving_intro_is_see_through(self):
        # The render lays it over the blurred match: only the words and logos.
        card = draw_title_card(
            Team("A"),
            Team("B"),
            CardText(tournament="Darmstadt"),
            size=SMALL,
            transparent=True,
        )

        assert card.getpixel((0, 0))[3] == 0
        assert painted(card) is not None

    def test_the_words_are_optional(self):
        bare = draw_title_card(Team("A"), Team("B"), size=SMALL)
        titled = draw_title_card(
            Team("A"), Team("B"), CardText(tournament="Darmstadt"), size=SMALL
        )

        assert bare.tobytes() != titled.tobytes()


class TestLogosAgainstTheEnds:
    """Both logos at the ends of the bar, whatever the names measure."""

    @pytest.fixture()
    def logos(self, tmp_path):
        paths = []
        for name, colour in (("a.png", (220, 60, 60)), ("b.png", (60, 60, 220))):
            path = tmp_path / name
            Image.new("RGBA", (120, 120), (*colour, 255)).save(path)
            paths.append(path)
        return paths

    @staticmethod
    def _logo_columns(image, colour):
        """Return the leftmost and rightmost column painted in `colour`."""
        pixels = np.asarray(image.convert("RGB"))
        columns = np.flatnonzero((pixels == colour).all(axis=2).any(axis=0))
        return (int(columns[0]), int(columns[-1])) if columns.size else None

    def test_they_sit_at_the_same_distance_from_the_middle(self, logos):
        # One short name, one long one: the logos must not follow the names.
        teams = {
            "team1": Team("Mécan'hydre de Darmstadt", logos[0]),
            "team2": Team("BK", logos[1]),
        }

        board = draw_scoreboard(state(), teams, size=SMALL)

        left = self._logo_columns(board, (220, 60, 60))
        right = self._logo_columns(board, (60, 60, 220))
        middle = SMALL[0] / 2
        assert middle - left[0] == pytest.approx(right[1] - middle, abs=2)

    def test_they_stay_inside_the_bar(self, logos):
        teams = {"team1": Team("A", logos[0]), "team2": Team("B", logos[1])}

        board = draw_scoreboard(state(), teams, size=SMALL)

        bar = painted(board)
        left = self._logo_columns(board, (220, 60, 60))
        right = self._logo_columns(board, (60, 60, 220))
        assert bar[0] <= left[0]
        assert right[1] <= bar[2]

    def test_a_longer_name_does_not_push_its_logo_outwards(self, logos):
        short = draw_scoreboard(
            state(),
            {"team1": Team("BK", logos[0]), "team2": Team("BK", logos[1])},
            size=SMALL,
        )
        long = draw_scoreboard(
            state(),
            {
                "team1": Team("Mécan'hydre de Darmstadt", logos[0]),
                "team2": Team("BK", logos[1]),
            },
            size=SMALL,
        )

        # The bar widens with the name, and the logo goes with the bar's end,
        # not with the end of the name.
        assert painted(long)[0] < painted(short)[0]
        assert self._logo_columns(long, (220, 60, 60))[0] == pytest.approx(
            painted(long)[0], abs=12
        )


class TestLogos:
    def test_a_missing_logo_is_not_an_error(self):
        assert load_logo(Path("/nowhere.png"), 40) is None
        assert load_logo(None, 40) is None

    def test_a_team_without_a_logo_gets_a_generated_one(self):
        # A missing file no longer leaves a hole: the bar keeps its shape.
        teams = {
            "team1": Team("A", Path("/nowhere.png")),
            "team2": Team("B", Path("/nowhere.png")),
        }
        with_logos = draw_scoreboard(state(), teams, size=SMALL)
        without = draw_scoreboard(state(), teams, show_logos=False, size=SMALL)

        assert painted(with_logos)[2] - painted(with_logos)[0] > (
            painted(without)[2] - painted(without)[0]
        )


class TestOneSizeForTheMatch:
    """The bar keeps its size and its names in place from point to point."""

    @staticmethod
    def _states():
        return [
            state(left_score=9, right_score=2),
            state(left_score=10, right_score=2),
            state(
                left_score=0,
                right_score=0,
                finished_sets=(SetScore(team1=10, team2=8),),
                set_number=2,
            ),
        ]

    def test_measured_one_state_at_a_time_the_bar_changes_size(self):
        # The bug: a second digit, or a closed set, widened the bar.
        boxes = {
            painted(draw_scoreboard(one, TEAMS, size=SMALL)) for one in self._states()
        }

        assert len(boxes) > 1

    def test_drawn_with_the_match_s_layout_it_keeps_one_size(self):
        states = self._states()
        layout = scoreboard_layout(states, TEAMS, size=SMALL)

        boxes = {
            painted(draw_scoreboard(one, TEAMS, size=SMALL, layout=layout))
            for one in states
        }

        assert len(boxes) == 1

    def test_the_names_do_not_move_when_a_score_gains_a_digit(self):
        states = self._states()[:2]
        layout = scoreboard_layout(states, TEAMS, size=SMALL)
        nine, ten = (
            np.asarray(draw_scoreboard(one, TEAMS, size=SMALL, layout=layout))
            for one in states
        )

        # Outside the score slots, the two images are the same pixels.
        differs = np.flatnonzero((nine != ten).any(axis=(0, 2)))
        centre = SMALL[0] // 2
        assert differs.size
        assert np.abs(differs - centre).max() < SMALL[0] * 0.08


class TestGeneratedLogo:
    def test_a_three_letter_short_name_is_kept_whole(self):
        from jugger_video_manipulation.overlay_render import _initials

        assert _initials("LND") == "LND"
        assert _initials("torpedo") == "TO"
        assert _initials("Munich Monks") == "MM"

    def test_three_letters_stay_inside_the_disc(self):
        logo = generated_logo("WWW", 64)

        # The letters are white, and so is the rim: look inside the rim only,
        # and the letters must keep clear of it.
        columns = [
            x for x in range(4, 60) if logo.getpixel((x, 32))[:3] == (255, 255, 255)
        ]
        assert columns
        assert min(columns) > 6
        assert max(columns) < 57

    def test_it_is_the_size_asked_for(self):
        assert generated_logo("Munich Monks", 64).size == (64, 64)

    def test_the_same_name_draws_the_same_logo(self):
        assert generated_logo("Torpedo Bääm!", 48).tobytes() == (
            generated_logo("Torpedo Bääm!", 48).tobytes()
        )

    def test_two_names_get_two_colours(self):
        first = generated_logo("Munich Monks", 48).getpixel((10, 24))
        second = generated_logo("Torpedo Bääm!", 48).getpixel((10, 24))

        assert first != second

    def test_the_corners_stay_transparent(self):
        # A disc, not a square: the bar shows through around it.
        assert generated_logo("NSA", 48).getpixel((0, 0))[3] == 0

    def test_a_real_logo_wins(self, tmp_path):
        path = tmp_path / "logo.png"
        Image.new("RGBA", (40, 20), (1, 2, 3, 255)).save(path)

        logo = team_logo(Team("A", path), 20)

        assert logo.size == (40, 20)
        assert logo.getpixel((20, 10)) == (1, 2, 3, 255)

    def test_the_short_name_gives_the_initials(self):
        with_short = team_logo(Team("Mécan'hydre", None, short_name="MH"), 48)
        from_name = team_logo(Team("Mécan'hydre", None), 48)

        assert with_short.tobytes() != from_name.tobytes()


class TestCardScalesWithTheFrame:
    """The card is laid out for 1080p and scaled, not pinned to pixel offsets."""

    @staticmethod
    def _ink_rows(card, size):
        """Return which rows carry drawn text, as fractions of the height."""
        grey = card.convert("L")
        rows = []
        for y in range(size[1]):
            band = grey.crop((0, y, size[0], y + 1))
            if band.getextrema()[1] > 200:
                rows.append(y / size[1])
        return rows

    def test_the_composition_survives_a_proxy_sized_frame(self):
        big = draw_title_card(
            Team("Mécan'hydre"),
            Team("Pink Pain"),
            CardText("Darmstadt", "2 sets gagnants"),
            size=(1920, 1080),
        )
        small = draw_title_card(
            Team("Mécan'hydre"),
            Team("Pink Pain"),
            CardText("Darmstadt", "2 sets gagnants"),
            size=(854, 480),
        )

        big_rows = self._ink_rows(big, (1920, 1080))
        small_rows = self._ink_rows(small, (854, 480))

        assert big_rows
        assert small_rows
        # Same composition: the text occupies the same band of the picture.
        assert small_rows[0] == pytest.approx(big_rows[0], abs=0.03)
        assert small_rows[-1] == pytest.approx(big_rows[-1], abs=0.03)

    def test_nothing_falls_off_the_bottom(self):
        card = draw_title_card(
            Team("Mécan'hydre"),
            Team("Pink Pain"),
            CardText("Darmstadt", "2 sets gagnants"),
            size=(854, 480),
        )

        rows = self._ink_rows(card, (854, 480))
        assert max(rows) < 0.98
