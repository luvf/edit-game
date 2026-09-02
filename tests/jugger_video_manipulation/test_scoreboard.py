"""Tests for the scoreboard state machine."""

from __future__ import annotations

import itertools

import pytest

from jugger_video_manipulation.scoreboard import (
    SetScore,
    build_states,
    place_segments,
    to_output_time,
)

FPS = 60.0


def point(start, end, scored=None):
    return {"in": start, "out": end, "point": scored}


class TestPlaceSegments:
    def test_the_first_point_starts_the_render(self):
        segments = place_segments([point(600, 1200)], FPS)

        assert segments[0].output_start == 0.0
        assert segments[0].output_end == pytest.approx(10.0)

    def test_dead_time_between_points_is_removed(self):
        # 10 s kept, a minute of dead time, 5 s kept.
        segments = place_segments([point(600, 1200), point(4800, 5100)], FPS)

        assert segments[1].output_start == pytest.approx(10.0)
        assert segments[1].output_end == pytest.approx(15.0)

    def test_an_empty_point_is_skipped(self):
        assert place_segments([point(600, 600)], FPS) == []

    def test_an_inverted_point_is_skipped(self):
        assert place_segments([point(1200, 600)], FPS) == []

    def test_an_unknown_side_is_not_a_score(self):
        segments = place_segments([point(0, 60, "nopoint")], FPS)

        assert segments[0].scored is None


class TestToOutputTime:
    @pytest.fixture()
    def segments(self):
        return place_segments([point(600, 1200), point(4800, 5100)], FPS)

    def test_a_frame_inside_a_point_keeps_its_offset(self, segments):
        # 300 frames into the first point, which starts the render.
        assert to_output_time(segments, 900, FPS) == pytest.approx(5.0)

    def test_a_frame_in_dead_time_lands_on_the_next_point(self, segments):
        assert to_output_time(segments, 3000, FPS) == pytest.approx(10.0)

    def test_a_frame_before_the_first_point_lands_at_the_start(self, segments):
        assert to_output_time(segments, 0, FPS) == 0.0

    def test_a_frame_past_the_last_point_is_dropped(self, segments):
        assert to_output_time(segments, 9000, FPS) is None

    def test_the_second_point_offsets_by_the_first(self, segments):
        assert to_output_time(segments, 4920, FPS) == pytest.approx(12.0)


class TestScoring:
    def test_a_point_on_the_left_goes_to_the_team_standing_there(self):
        states = build_states(
            [point(0, 60, "left"), point(60, 120)],
            {"start_sides": {"left": "team1", "right": "team2"}},
            FPS,
        )

        assert (states[-1].left_score, states[-1].right_score) == (1, 0)

    def test_the_board_shows_the_score_the_point_started_at(self):
        states = build_states([point(0, 60, "left"), point(60, 120)], {}, FPS)

        assert (states[0].left_score, states[0].right_score) == (0, 0)

    def test_a_side_switch_moves_the_teams_not_the_scores(self):
        states = build_states(
            [point(0, 60, "left"), point(600, 660)],
            {
                "start_sides": {"left": "team1", "right": "team2"},
                "events": [{"type": "side_switch", "tc": 300}],
            },
            FPS,
        )

        last = states[-1]
        assert (last.left, last.right) == ("team2", "team1")
        # team1 scored, and is now on the right.
        assert (last.left_score, last.right_score) == (0, 1)

    def test_two_switches_return_to_the_start(self):
        states = build_states(
            [point(0, 60), point(600, 660)],
            {
                "start_sides": {"left": "team1", "right": "team2"},
                "events": [
                    {"type": "side_switch", "tc": 100},
                    {"type": "side_switch", "tc": 200},
                ],
            },
            FPS,
        )

        assert (states[-1].left, states[-1].right) == ("team1", "team2")

    def test_a_set_end_banks_the_score_and_resets(self):
        states = build_states(
            [point(0, 60, "left"), point(60, 120, "left"), point(600, 660)],
            {
                "start_sides": {"left": "team1", "right": "team2"},
                "events": [{"type": "set_end", "tc": 300}],
            },
            FPS,
        )

        last = states[-1]
        assert last.finished_sets == (SetScore(team1=2, team2=0),)
        assert (last.left_score, last.right_score) == (0, 0)
        assert last.set_number == 2

    def test_the_default_sides_are_team1_left(self):
        states = build_states([point(0, 60, "left"), point(60, 120)], {}, FPS)

        assert states[0].left == "team1"


class TestStateStream:
    def test_states_cover_the_render_without_gaps(self):
        states = build_states(
            [point(0, 60, "left"), point(600, 660, "right"), point(1200, 1260)],
            {},
            FPS,
        )

        for previous, following in itertools.pairwise(states):
            assert previous.end == pytest.approx(following.start)
        assert states[0].start == 0.0

    def test_identical_consecutive_states_are_merged(self):
        # Three points where nobody scores: one state, not three.
        states = build_states(
            [point(0, 60), point(600, 660), point(1200, 1260)], {}, FPS
        )

        assert len(states) == 1
        assert states[0].end == pytest.approx(3.0)

    def test_a_score_splits_the_stream(self):
        states = build_states([point(0, 60, "left"), point(600, 660)], {}, FPS)

        assert len(states) == 2

    def test_no_points_gives_no_states(self):
        assert build_states([], {}, FPS) == []

    def test_hold_final_keeps_the_closing_score_on_screen(self):
        states = build_states([point(0, 60, "left")], {}, FPS, hold_final=3.0)

        assert states[-1].left_score == 1
        assert states[-1].duration == pytest.approx(3.0)

    def test_without_hold_the_last_point_result_is_not_shown(self):
        states = build_states([point(0, 60, "left")], {}, FPS)

        assert states[-1].left_score == 0


class TestSetScore:
    def test_it_names_the_winner(self):
        assert SetScore(7, 5).winner == "team1"
        assert SetScore(5, 7).winner == "team2"

    def test_a_tie_has_no_winner(self):
        assert SetScore(7, 7).winner is None
