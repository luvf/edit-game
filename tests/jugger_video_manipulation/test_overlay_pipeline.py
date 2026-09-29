"""Tests for the join between the cut file and the render."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image

from jugger_video_manipulation.overlay_pipeline import (
    CutContent,
    Intro,
    OverlayPlan,
    RenderContext,
    Window,
    build_plan,
)
from jugger_video_manipulation.overlay_render import Team
from jugger_video_manipulation.scoreboard import Timing

FPS = 60.0
SMALL = (480, 270)
TEAMS = {"team1": Team("Mécan'hydre"), "team2": Team("Pink Pain")}
CONTEXT = RenderContext(size=SMALL)


def point(start, end, scored=None):
    return {"in": start, "out": end, "point": scored}


def warning(tc, length=None):
    item = {"type": "Warning", "warning_type": "replay", "text": "x", "tc": tc}
    if length is not None:
        item["length"] = length
    return item


def box(window):
    """Return where a window's image is painted, to tell two rows apart."""
    return Image.open(window.path).getchannel("A").getbbox()


class TestScoreboardWindows:
    def test_a_cut_that_never_says_who_scored_gets_no_board(self, tmp_path):
        plan = build_plan(
            CutContent(points=[point(0, 60), point(600, 660)]),
            TEAMS,
            FPS,
            tmp_path,
            context=CONTEXT,
        )

        assert plan.windows == []

    def test_a_starting_score_is_enough(self, tmp_path):
        plan = build_plan(
            CutContent(
                points=[point(0, 60), point(600, 660)],
                start_score={"team1": [3], "team2": [2]},
                display={"intro": False},
            ),
            TEAMS,
            FPS,
            tmp_path,
            context=CONTEXT,
        )

        assert len(plan.windows) == 1

    def test_one_scored_point_is_enough(self, tmp_path):
        plan = build_plan(
            CutContent(points=[point(0, 60, "left")]),
            TEAMS,
            FPS,
            tmp_path,
            context=CONTEXT,
        )

        assert len(plan.windows) == 1

    def test_one_image_per_state(self, tmp_path):
        content = CutContent(
            points=[point(0, 60, "left"), point(600, 660, "right"), point(1200, 1260)]
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert len(plan.windows) == 3
        assert all(window.path.exists() for window in plan.windows)

    def test_the_windows_cover_the_render_without_gaps(self, tmp_path):
        content = CutContent(points=[point(0, 60, "left"), point(600, 660, "right")])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows[0].start == 0.0
        assert plan.windows[0].end == pytest.approx(plan.windows[1].start)

    def test_the_images_are_the_requested_size(self, tmp_path):
        content = CutContent(points=[point(0, 60, "left")])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert Image.open(plan.windows[0].path).size == SMALL


class TestWarnings:
    def test_a_warning_inside_a_point_keeps_its_offset(self, tmp_path):
        content = CutContent(points=[point(0, 600)], overlays=[warning(300)])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows[0].start == pytest.approx(5.0)

    def test_a_warning_in_dead_time_waits_for_the_next_point(self, tmp_path):
        content = CutContent(
            points=[point(0, 60), point(600, 660)], overlays=[warning(300)]
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows[0].start == pytest.approx(1.0)

    def test_a_warning_past_the_last_point_is_dropped(self, tmp_path):
        content = CutContent(points=[point(0, 60)], overlays=[warning(9000)])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows == []

    def test_two_warnings_at_once_are_drawn_one_above_the_other(self, tmp_path):
        content = CutContent(
            points=[point(0, 600)],
            overlays=[warning(0, length=300), warning(60, length=300)],
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        first, second = (box(window) for window in plan.windows)
        assert first != second
        # Both stay up in full: they move apart, they are not cut short.
        assert plan.windows[0].duration == pytest.approx(5.0)
        assert plan.windows[1].duration == pytest.approx(5.0)

    def test_a_warning_that_waits_its_turn_takes_the_free_row(self, tmp_path):
        content = CutContent(
            points=[point(0, 1800)],
            overlays=[warning(0, length=300), warning(600, length=300)],
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        first, second = (box(window) for window in plan.windows)
        assert first == second

    def test_the_length_is_read_in_frames(self, tmp_path):
        content = CutContent(points=[point(0, 600)], overlays=[warning(0, length=300)])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows[0].duration == pytest.approx(5.0)


class TestIntro:
    def test_two_teams_are_enough_for_a_card(self, tmp_path):
        content = CutContent(points=[point(0, 60)])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.intro is not None
        assert plan.intro.path.exists()

    def test_its_length_is_read_in_frames(self, tmp_path):
        content = CutContent(
            points=[point(0, 60)],
            display={"title_card": {"length": 180}},
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.intro.duration == pytest.approx(3.0)

    def test_one_team_missing_means_no_card(self, tmp_path):
        content = CutContent(points=[point(0, 60)])

        plan = build_plan(content, {"team1": Team("A")}, FPS, tmp_path, context=CONTEXT)

        assert plan.intro is None


class TestCardDissolvesIntoTheMatch:
    """The card does not vanish: the match comes up through it."""

    def test_the_card_carries_the_transition_asked_for(self, tmp_path):
        content = CutContent(points=[point(0, 600)])

        plan = build_plan(
            content, TEAMS, FPS, tmp_path, context=CONTEXT, timing=Timing(crossfade=1.0)
        )

        assert plan.intro.fade == pytest.approx(1.0)

    def test_a_short_card_dissolves_for_half_of_itself(self, tmp_path):
        content = CutContent(
            points=[point(0, 600)],
            display={"title_card": {"length": 60}},
        )

        plan = build_plan(
            content, TEAMS, FPS, tmp_path, context=CONTEXT, timing=Timing(crossfade=1.0)
        )

        assert plan.intro.duration == pytest.approx(1.0)
        assert plan.intro.fade == pytest.approx(0.5)

    def test_the_match_starts_when_the_dissolve_starts(self):
        plan = OverlayPlan(intro=Intro(Path("/card.png"), 4.0, fade=1.0))

        assert plan.offset == pytest.approx(3.0)

    def test_the_boards_are_placed_on_the_shortened_timeline(self, tmp_path):
        content = CutContent(points=[point(0, 600, "left"), point(1200, 1800, "right")])

        plan = build_plan(
            content, TEAMS, FPS, tmp_path, context=CONTEXT, timing=Timing(crossfade=1.0)
        )

        # The second point starts at 9 s, one second into the dissolve; its
        # board takes over halfway, so the two never show together.
        assert plan.windows[1].start == pytest.approx(9.5)

    def test_a_warning_follows_the_same_timeline(self, tmp_path):
        content = CutContent(
            points=[point(0, 600), point(1200, 1800)],
            overlays=[warning(1200)],
        )

        plan = build_plan(
            content, TEAMS, FPS, tmp_path, context=CONTEXT, timing=Timing(crossfade=1.0)
        )

        assert plan.windows[0].start == pytest.approx(9.0)


class TestPlanArguments:
    """What the plan hands ffmpeg has to line up with the inputs it adds."""

    def test_the_card_comes_first_among_the_files(self):
        plan = OverlayPlan(
            windows=[Window(Path("/b.png"), 0.0, 1.0)],
            intro=Intro(Path("/card.png"), 4.0),
        )

        assert plan.files()[0] == Path("/card.png")

    def test_windows_are_offset_by_the_card(self):
        plan = OverlayPlan(
            windows=[Window(Path("/b.png"), 0.0, 1.0)],
            intro=Intro(Path("/card.png"), 4.0),
        )

        assert plan.overlay_arguments(2) == [(3, 4.0, 5.0)]

    def test_without_a_card_nothing_is_offset(self):
        plan = OverlayPlan(windows=[Window(Path("/b.png"), 0.0, 1.0)])

        assert plan.overlay_arguments(2) == [(2, 0.0, 1.0)]

    def test_indices_follow_the_file_order(self):
        plan = OverlayPlan(
            windows=[Window(Path("/a.png"), 0.0, 1.0), Window(Path("/b.png"), 1.0, 2.0)]
        )

        assert [index for index, _, _ in plan.overlay_arguments(5)] == [5, 6]


class TestTail:
    """The video runs on after the last point, with its result on the board."""

    def test_the_final_score_stays_up_over_the_tail(self, tmp_path):
        content = CutContent(points=[point(0, 600, "left"), point(1200, 1800, "left")])

        plan = build_plan(
            content,
            TEAMS,
            FPS,
            tmp_path,
            context=CONTEXT,
            timing=Timing(tail_frames=1500),
        )

        # Ten seconds, ten seconds, then the 25 s tail on a board of its own.
        assert [round(window.start, 3) for window in plan.windows] == [0.0, 10.0, 20.0]
        assert plan.windows[-1].end == pytest.approx(45.0)

    def test_a_warning_during_the_tail_is_shown(self, tmp_path):
        # Without a tail it would fall past the last point and be dropped.
        content = CutContent(points=[point(0, 600)], overlays=[warning(900)])

        plan = build_plan(
            content,
            TEAMS,
            FPS,
            tmp_path,
            context=CONTEXT,
            timing=Timing(tail_frames=1500),
        )

        assert plan.windows[0].start == pytest.approx(15.0)


class TestIntroSwitch:
    """The editor can turn the opening card off."""

    def test_the_card_is_on_by_default(self, tmp_path):
        content = CutContent(points=[point(0, 60)])

        assert build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT).intro

    def test_an_explicit_no_drops_it(self, tmp_path):
        content = CutContent(
            points=[point(0, 60)],
            display={"intro": False},
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.intro is None
        assert plan.offset == 0.0


class TestBoardsAcrossTheMatch:
    def test_every_board_of_a_match_is_the_same_size(self, tmp_path):
        points = [point(i * 600, i * 600 + 300, "left") for i in range(12)]
        content = CutContent(points=points, overlays=[{"type": "SetEnd", "tc": 3050}])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        boxes = {
            Image.open(window.path).getchannel("A").getbbox() for window in plan.windows
        }
        assert len(plan.windows) > 3
        assert len(boxes) == 1

    def test_boards_never_overlap_across_a_dissolve(self, tmp_path):
        points = [point(i * 900, i * 900 + 600, "left") for i in range(4)]

        plan = build_plan(
            CutContent(points=points),
            TEAMS,
            FPS,
            tmp_path,
            context=CONTEXT,
            timing=Timing(crossfade=1.0),
        )

        windows = sorted(plan.windows, key=lambda window: window.start)
        for current, following in pairwise(windows):
            assert following.start >= current.end


class TestMovingIntro:
    """Behind the card, the seconds before the first point, dissolving into it."""

    @staticmethod
    def _plan(tmp_path, points, **display):
        content = CutContent(
            points=points,
            display={"title_card": display} if display else {},
        )
        return build_plan(
            content, TEAMS, FPS, tmp_path, context=CONTEXT, timing=Timing(crossfade=1.0)
        )

    def test_the_footage_starts_before_the_first_point(self, tmp_path):
        plan = self._plan(tmp_path, [point(6000, 6600, "left")])

        # Four seconds of card, the last of which is the dissolve: three
        # seconds of footage before the point, 180 frames at 60 fps.
        assert plan.intro.source_start == 6000 - 180
        assert plan.intro.duration == pytest.approx(4.0)

    def test_the_dissolve_starts_on_the_first_point(self, tmp_path):
        plan = self._plan(tmp_path, [point(6000, 6600, "left")])

        # The match, and every overlay on it, starts when the dissolve does.
        assert plan.offset == pytest.approx((6000 - plan.intro.source_start) / FPS)

    def test_a_point_close_to_the_start_shortens_the_card(self, tmp_path):
        plan = self._plan(tmp_path, [point(90, 600, "left")])

        # Only a second and a half before the point: that, plus the dissolve.
        assert plan.intro.source_start == 0
        assert plan.intro.duration == pytest.approx(1.5 + 1.0)

    def test_too_little_footage_keeps_a_still_card(self, tmp_path):
        plan = self._plan(tmp_path, [point(30, 600, "left")])

        assert plan.intro.source_start is None
        assert plan.intro.duration == pytest.approx(4.0)

    def test_a_flat_card_stays_still(self, tmp_path):
        plan = self._plan(tmp_path, [point(6000, 6600, "left")], background="flat")

        assert plan.intro.source_start is None

    def test_the_first_kept_point_is_the_one_that_counts(self, tmp_path):
        plan = self._plan(tmp_path, [point(500, 500), point(6000, 6600, "left")])

        assert plan.intro.source_start == 6000 - 180

    def test_the_card_over_footage_is_see_through(self, tmp_path):
        moving = self._plan(tmp_path, [point(6000, 6600, "left")])
        still_dir = tmp_path / "still"
        still = self._plan(still_dir, [point(6000, 6600, "left")], background="flat")

        assert Image.open(moving.intro.path).getpixel((0, 0))[3] == 0
        assert Image.open(still.intro.path).getpixel((0, 0))[3] == 255
