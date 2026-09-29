"""Tests for the scoreboard state machine."""

from __future__ import annotations

import itertools
from itertools import pairwise

import pytest

from jugger_video_manipulation.scoreboard import (
    SetScore,
    build_states,
    crossfade_durations,
    extend_last,
    place_segments,
    start_score,
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


class TestCrossfade:
    """A transition makes two points share seconds, so the render is shorter."""

    def test_the_second_point_starts_before_the_first_has_ended(self):
        segments = place_segments(
            [point(0, 600), point(1200, 1800)], FPS, crossfade=1.0
        )

        assert segments[0].output_end == pytest.approx(10.0)
        assert segments[1].output_start == pytest.approx(9.0)
        assert segments[1].output_end == pytest.approx(19.0)

    def test_every_transition_shortens_what_follows(self):
        segments = place_segments(
            [point(0, 600), point(1200, 1800), point(2400, 3000)], FPS, crossfade=1.0
        )

        # Three ten-second points, two transitions: 30 - 2 = 28.
        assert segments[-1].output_end == pytest.approx(28.0)

    def test_no_crossfade_places_the_points_end_to_end(self):
        segments = place_segments([point(0, 600), point(1200, 1800)], FPS)

        assert segments[1].output_start == pytest.approx(10.0)

    def test_the_board_follows_the_picture(self):
        states = build_states(
            [point(0, 600, "left"), point(1200, 1800, "right")], FPS, crossfade=1.0
        )

        # The picture's second point starts at 9 s; the board changes
        # halfway through the dissolve.
        assert states[1].start == pytest.approx(9.5)

    def test_one_length_per_join(self):
        points = [point(0, 600), point(1200, 1800), point(2400, 3000)]

        assert len(crossfade_durations(points, FPS, 1.0)) == 2

    def test_a_single_point_has_nothing_to_join(self):
        assert crossfade_durations([point(0, 600)], FPS, 1.0) == []

    def test_a_transition_never_takes_more_than_half_a_point(self):
        # The middle point lasts half a second: a full second of transition
        # on each side would leave nothing of it, and xfade would refuse it.
        points = [point(0, 600), point(1200, 1230), point(2400, 3000)]

        assert crossfade_durations(points, FPS, 1.0) == [0.25, 0.25]

    def test_asking_for_none_gives_zeros_rather_than_nothing(self):
        # One value per join, always: the caller indexes them by join.
        assert crossfade_durations([point(0, 600), point(1200, 1800)], FPS, 0.0) == [
            0.0
        ]

    def test_points_that_keep_nothing_are_not_joins(self):
        points = [point(0, 600), point(1200, 1200), point(2400, 3000)]

        assert len(crossfade_durations(points, FPS, 1.0)) == 1


class TestBoardsDuringATransition:
    """The picture dissolves; the board changes once, and never doubles up."""

    def test_two_boards_meet_halfway_through_the_dissolve(self):
        states = build_states(
            [point(0, 600, "left"), point(1200, 1800, "left")], FPS, crossfade=1.0
        )

        # The first point ends at 10 s, the second starts at 9 s: they meet at 9.5.
        assert states[0].end == pytest.approx(9.5)
        assert states[1].start == pytest.approx(9.5)

    def test_no_two_boards_share_a_second(self):
        points = [point(0, 600, "left"), point(1200, 1800, "right"), point(2400, 3000)]

        states = build_states(points, FPS, crossfade=1.0)

        for current, following in pairwise(states):
            assert following.start >= current.end

    def test_without_a_transition_boards_already_meet(self):
        states = build_states([point(0, 600, "left"), point(1200, 1800)], FPS)

        assert states[0].end == pytest.approx(states[1].start)


class TestTail:
    """The render runs on after the last point, the board showing the result."""

    def test_the_last_point_runs_on(self):
        points = extend_last([point(0, 600), point(1200, 1800)], 300)

        assert [p["out"] for p in points] == [600, 2100]

    def test_the_points_as_edited_are_left_alone(self):
        points = [point(0, 600)]

        extend_last(points, 300)

        assert points[0]["out"] == 600

    def test_a_point_that_keeps_nothing_is_not_the_one_extended(self):
        points = extend_last([point(0, 600), point(900, 900)], 300)

        assert [p["out"] for p in points] == [900, 900]

    def test_the_tail_lengthens_the_last_segment(self):
        segments = place_segments([point(0, 600)], FPS, tail_frames=1500)

        assert segments[0].output_end == pytest.approx(35.0)

    def test_the_last_point_s_board_stops_where_the_point_did(self):
        states = build_states([point(0, 600, "left")], FPS, tail_frames=1500)

        assert states[0].end == pytest.approx(10.0)
        assert states[0].left_score == 0

    def test_the_tail_shows_the_last_point_counted(self):
        states = build_states([point(0, 600, "left")], FPS, tail_frames=1500)

        assert (states[-1].start, states[-1].end) == (
            pytest.approx(10.0),
            pytest.approx(35.0),
        )
        assert states[-1].left_score == 1

    def test_a_set_closed_after_the_last_point_does_not_empty_the_board(self):
        # The match is over: 0-0 with a banked set would be the wrong thing to
        # leave on screen for 25 seconds.
        states = build_states(
            [point(0, 600, "left")],
            FPS,
            overlays=[{"type": "SetEnd", "tc": 700}],
            tail_frames=1500,
        )

        assert states[-1].left_score == 1
        assert states[-1].finished_sets == ()

    def test_without_a_tail_nothing_changes(self):
        states = build_states([point(0, 600, "left")], FPS)

        assert len(states) == 1
        assert states[0].end == pytest.approx(10.0)


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
        states = build_states([point(0, 60, "left"), point(60, 120)], FPS)

        assert (states[-1].left_score, states[-1].right_score) == (1, 0)

    def test_the_board_shows_the_score_the_point_started_at(self):
        states = build_states([point(0, 60, "left"), point(60, 120)], FPS)

        assert (states[0].left_score, states[0].right_score) == (0, 0)

    def test_a_side_switch_moves_the_teams_not_the_scores(self):
        states = build_states(
            [point(0, 60, "left"), point(600, 660)],
            FPS,
            overlays=[{"type": "SideSwitch", "tc": 300}],
        )

        last = states[-1]
        assert (last.left, last.right) == ("team2", "team1")
        # team1 scored, and is now on the right.
        assert (last.left_score, last.right_score) == (0, 1)

    def test_two_switches_return_to_the_start(self):
        states = build_states(
            [point(0, 60), point(600, 660)],
            FPS,
            overlays=[
                {"type": "SideSwitch", "tc": 100},
                {"type": "SideSwitch", "tc": 200},
            ],
        )

        assert (states[-1].left, states[-1].right) == ("team1", "team2")

    def test_a_set_end_banks_the_score_and_resets(self):
        states = build_states(
            [point(0, 60, "left"), point(60, 120, "left"), point(600, 660)],
            FPS,
            overlays=[{"type": "SetEnd", "tc": 300}],
        )

        last = states[-1]
        assert last.finished_sets == (SetScore(team1=2, team2=0),)
        assert (last.left_score, last.right_score) == (0, 0)
        assert last.set_number == 2

    def test_team_one_starts_on_the_left(self):
        states = build_states([point(0, 60, "left"), point(60, 120)], FPS)

        assert states[0].left == "team1"


class TestStateStream:
    def test_states_cover_the_render_without_gaps(self):
        states = build_states(
            [point(0, 60, "left"), point(600, 660, "right"), point(1200, 1260)],
            FPS,
        )

        for previous, following in itertools.pairwise(states):
            assert previous.end == pytest.approx(following.start)
        assert states[0].start == 0.0

    def test_identical_consecutive_states_are_merged(self):
        # Three points where nobody scores: one state, not three.
        states = build_states([point(0, 60), point(600, 660), point(1200, 1260)], FPS)

        assert len(states) == 1
        assert states[0].end == pytest.approx(3.0)

    def test_a_score_splits_the_stream(self):
        states = build_states([point(0, 60, "left"), point(600, 660)], FPS)

        assert len(states) == 2

    def test_no_points_gives_no_states(self):
        assert build_states([], FPS) == []

    def test_hold_final_keeps_the_closing_score_on_screen(self):
        states = build_states([point(0, 60, "left")], FPS, hold_final=3.0)

        assert states[-1].left_score == 1
        assert states[-1].duration == pytest.approx(3.0)

    def test_without_hold_the_last_point_result_is_not_shown(self):
        states = build_states([point(0, 60, "left")], FPS)

        assert states[-1].left_score == 0


class TestSetScore:
    def test_it_names_the_winner(self):
        assert SetScore(7, 5).winner == "team1"
        assert SetScore(5, 7).winner == "team2"

    def test_a_tie_has_no_winner(self):
        assert SetScore(7, 7).winner is None


class TestEventsFromOverlays:
    """Side switches and set ends are edited among the overlays."""

    def test_a_side_switch_overlay_swaps_the_teams(self):
        states = build_states(
            [point(0, 60), point(600, 660)],
            FPS,
            overlays=[{"type": "SideSwitch", "tc": 300}],
        )

        assert (states[-1].left, states[-1].right) == ("team2", "team1")

    def test_a_set_end_overlay_banks_the_score(self):
        states = build_states(
            [point(0, 60, "left"), point(600, 660)],
            FPS,
            overlays=[{"type": "SetEnd", "tc": 300}],
        )

        assert states[-1].finished_sets == (SetScore(team1=1, team2=0),)

    def test_other_overlays_are_ignored(self):
        states = build_states(
            [point(0, 60), point(600, 660)],
            FPS,
            overlays=[
                {"type": "Warning", "warning_type": "replay", "text": "x", "tc": 300},
                {"type": "TeamIntroduction", "team1": "a", "team2": "b"},
            ],
        )

        assert (states[-1].left, states[-1].right) == ("team1", "team2")

    def test_events_from_both_places_are_ordered_together(self):
        from jugger_video_manipulation.scoreboard import score_events

        events = score_events(
            [{"type": "SetEnd", "tc": 900}, {"type": "SideSwitch", "tc": 300}]
        )

        assert [event["tc"] for event in events] == [300, 900]

    def test_the_overlay_names_map_onto_the_event_names(self):
        from jugger_video_manipulation.scoreboard import score_events

        events = score_events(
            [{"type": "SideSwitch", "tc": 1}, {"type": "SetEnd", "tc": 2}]
        )

        assert [event["type"] for event in events] == ["side_switch", "set_end"]


class TestStartScore:
    """A recording that misses the start of the match is given the score it missed."""

    def test_the_board_starts_at_the_given_score(self):
        states = build_states(
            [point(0, 60, "left"), point(600, 660)],
            FPS,
            start={"team1": [3], "team2": [2]},
        )

        assert (states[0].left_score, states[0].right_score) == (3, 2)
        assert (states[-1].left_score, states[-1].right_score) == (4, 2)

    def test_earlier_numbers_are_finished_sets(self):
        states = build_states(
            [point(0, 60)], FPS, start={"team1": [10, 3], "team2": [8, 0]}
        )

        assert states[0].finished_sets == (SetScore(team1=10, team2=8),)
        assert states[0].set_number == 2
        assert (states[0].left_score, states[0].right_score) == (3, 0)

    def test_a_side_switch_moves_the_starting_score_with_its_team(self):
        states = build_states(
            [point(600, 660)],
            FPS,
            overlays=[{"type": "SideSwitch", "tc": 0}],
            start={"team1": [3], "team2": [2]},
        )

        assert (states[0].left_score, states[0].right_score) == (2, 3)

    def test_no_start_score_starts_at_zero(self):
        states = build_states([point(0, 60)], FPS)

        assert (states[0].left_score, states[0].right_score) == (0, 0)


class TestPairingStartScores:
    """One number per set for each team, typed or stored."""

    def test_the_shorter_team_is_padded_with_zeros_on_the_right(self):
        assert start_score([10, 3], [8]) == {"team1": [10, 3], "team2": [8, 0]}

    def test_text_uses_a_dash_between_sets(self):
        assert start_score("10-3", "8") == {"team1": [10, 3], "team2": [8, 0]}

    def test_nothing_on_either_side_is_no_start_score(self):
        assert start_score("", []) is None

    def test_what_is_not_a_number_counts_as_zero(self):
        assert start_score(["x", -2, 4], [1]) == {
            "team1": [0, 0, 4],
            "team2": [1, 0, 0],
        }
