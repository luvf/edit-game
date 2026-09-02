"""Tests for the join between the cut file and the render."""

from __future__ import annotations

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

    def test_the_length_is_read_in_frames(self, tmp_path):
        content = CutContent(points=[point(0, 600)], overlays=[warning(0, length=300)])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows[0].duration == pytest.approx(5.0)

    def test_a_team_introduction_is_not_a_warning(self, tmp_path):
        content = CutContent(points=[point(0, 600)], overlays=[{"type": "GameInfo"}])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.windows == []


class TestIntro:
    def test_no_card_unless_the_file_asks(self, tmp_path):
        plan = build_plan(
            CutContent(points=[point(0, 60)]), TEAMS, FPS, tmp_path, context=CONTEXT
        )

        assert plan.intro is None
        assert plan.offset == 0.0

    def test_a_team_introduction_produces_a_card(self, tmp_path):
        content = CutContent(points=[point(0, 60)], overlays=[{"type": "GameInfo"}])

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.intro is not None
        assert plan.intro.path.exists()

    def test_its_length_is_read_in_frames(self, tmp_path):
        content = CutContent(
            points=[point(0, 60)],
            overlays=[{"type": "GameInfo"}],
            display={"title_card": {"length": 180}},
        )

        plan = build_plan(content, TEAMS, FPS, tmp_path, context=CONTEXT)

        assert plan.intro.duration == pytest.approx(3.0)

    def test_one_team_missing_means_no_card(self, tmp_path):
        content = CutContent(points=[point(0, 60)], overlays=[{"type": "GameInfo"}])

        plan = build_plan(content, {"team1": Team("A")}, FPS, tmp_path, context=CONTEXT)

        assert plan.intro is None


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
