"""Tests for jugger_video_manipulation.cut_json_parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from jugger_video_manipulation.cut_json_parser import CutJsonParser

if TYPE_CHECKING:
    from pathlib import Path


class TestLoad:
    def test_returns_defaults_when_file_missing(self, tmp_path: Path):
        parser = CutJsonParser(tmp_path / "missing.json")
        assert parser.load() == {"points": [], "overlays": []}

    def test_reads_existing_file(self, tmp_path: Path):
        path = tmp_path / "cut.json"
        path.write_text(json.dumps({"points": [{"in": 1, "out": 2}], "overlays": []}))
        parser = CutJsonParser(path)
        assert parser.load() == {"points": [{"in": 1, "out": 2}], "overlays": []}


class TestParsePoints:
    def setup_method(self):
        self.parser = CutJsonParser("unused.json")

    def test_parses_valid_points(self):
        raw = {"points": [{"in": "10", "out": 20, "point": "left"}]}
        assert self.parser.parse_points(raw) == [{"in": 10, "out": 20, "point": "left"}]

    def test_defaults_missing_fields(self):
        raw = {"points": [{}]}
        assert self.parser.parse_points(raw) == [{"in": 0, "out": 0, "point": None}]

    def test_drops_non_dict_entries(self):
        raw = {"points": ["not-a-dict", {"in": 1, "out": 2}]}
        assert self.parser.parse_points(raw) == [{"in": 1, "out": 2, "point": None}]

    def test_drops_entries_with_unparseable_numbers(self):
        raw = {"points": [{"in": "abc", "out": 2}]}
        assert self.parser.parse_points(raw) == []

    def test_normalizes_invalid_point_value_to_none(self):
        raw = {"points": [{"in": 1, "out": 2, "point": "invalid"}]}
        assert self.parser.parse_points(raw) == [{"in": 1, "out": 2, "point": None}]

    def test_missing_points_key_returns_empty_list(self):
        assert self.parser.parse_points({}) == []


class TestParseOverlays:
    def setup_method(self):
        self.parser = CutJsonParser("unused.json")

    def test_parses_team_introduction_overlay(self):
        raw = {
            "overlays": [
                {
                    "type": "TeamIntroduction",
                    "team1": "Alpha",
                    "team2": "Beta",
                    "condition": "start",
                }
            ]
        }
        assert self.parser.parse_overlays(raw) == [
            {
                "type": "TeamIntroduction",
                "team1": "Alpha",
                "team2": "Beta",
                "condition": "start",
            }
        ]

    def test_parses_warning_overlay_with_length(self):
        raw = {
            "overlays": [
                {
                    "type": "Warning",
                    "warning_type": "yellow",
                    "text": "foul",
                    "tc": "42",
                    "length": "5",
                }
            ]
        }
        assert self.parser.parse_overlays(raw) == [
            {
                "type": "Warning",
                "warning_type": "yellow",
                "text": "foul",
                "tc": 42,
                "length": 5,
            }
        ]

    def test_warning_overlay_without_length_omits_key(self):
        raw = {
            "overlays": [
                {"type": "Warning", "warning_type": "red", "text": "x", "tc": 0}
            ]
        }
        (overlay,) = self.parser.parse_overlays(raw)
        assert "length" not in overlay

    def test_warning_overlay_bad_tc_defaults_to_zero(self):
        raw = {
            "overlays": [
                {"type": "Warning", "warning_type": "red", "text": "x", "tc": "n/a"}
            ]
        }
        (overlay,) = self.parser.parse_overlays(raw)
        assert overlay["tc"] == 0

    def test_unknown_overlay_type_is_dropped(self):
        raw = {"overlays": [{"type": "Unknown"}]}
        assert self.parser.parse_overlays(raw) == []


class TestParse:
    def test_parse_combines_load_and_parsing(self, tmp_path: Path):
        path = tmp_path / "cut.json"
        path.write_text(
            json.dumps(
                {
                    "points": [{"in": 0, "out": 10}],
                    "overlays": [{"type": "Unknown"}],
                }
            )
        )
        points, overlays = CutJsonParser(path).parse()
        assert points == [{"in": 0, "out": 10, "point": None}]
        assert overlays == []


class TestParseMatch:
    """The block the scoreboard is computed from."""

    def test_a_file_without_a_match_block_parses_empty(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"points": [], "overlays": []}))

        assert CutJsonParser(path).parse_match(json.loads(path.read_text())) == {}

    def test_it_reads_the_winning_condition(self, tmp_path):
        raw = {"match": {"winning_condition": {"type": "sets", "sets_to_win": 3}}}

        parsed = CutJsonParser(tmp_path / "c.json").parse_match(raw)

        assert parsed["winning_condition"] == {"type": "sets", "sets_to_win": 3}

    def test_an_unknown_condition_type_is_dropped(self, tmp_path):
        raw = {"match": {"winning_condition": {"type": "coinflip"}}}

        assert "winning_condition" not in CutJsonParser(tmp_path / "c").parse_match(raw)

    def test_it_reads_the_starting_sides(self, tmp_path):
        raw = {"match": {"start_sides": {"left": "team2", "right": "team1"}}}

        parsed = CutJsonParser(tmp_path / "c").parse_match(raw)

        assert parsed["start_sides"] == {"left": "team2", "right": "team1"}

    def test_half_a_side_mapping_is_dropped(self, tmp_path):
        raw = {"match": {"start_sides": {"left": "team1"}}}

        assert "start_sides" not in CutJsonParser(tmp_path / "c").parse_match(raw)

    def test_events_are_sorted_by_timecode(self, tmp_path):
        raw = {
            "match": {
                "events": [
                    {"type": "set_end", "tc": 900},
                    {"type": "side_switch", "tc": 300},
                ]
            }
        }

        parsed = CutJsonParser(tmp_path / "c").parse_match(raw)

        assert [e["tc"] for e in parsed["events"]] == [300, 900]

    def test_an_unknown_event_type_is_dropped(self, tmp_path):
        raw = {"match": {"events": [{"type": "coffee_break", "tc": 10}]}}

        assert "events" not in CutJsonParser(tmp_path / "c").parse_match(raw)

    def test_an_event_without_a_timecode_is_dropped(self, tmp_path):
        raw = {"match": {"events": [{"type": "set_end"}]}}

        assert "events" not in CutJsonParser(tmp_path / "c").parse_match(raw)


class TestParseDisplay:
    """Editing choices, kept apart from what happened in the match."""

    def test_absent_block_parses_empty(self, tmp_path):
        assert CutJsonParser(tmp_path / "c").parse_display({}) == {}

    def test_it_reads_the_scoreboard_position(self, tmp_path):
        raw = {"display": {"scoreboard": {"position": "top"}}}

        parsed = CutJsonParser(tmp_path / "c").parse_display(raw)

        assert parsed["scoreboard"]["position"] == "top"

    def test_an_unknown_position_is_dropped(self, tmp_path):
        raw = {"display": {"scoreboard": {"position": "sideways"}}}

        assert CutJsonParser(tmp_path / "c").parse_display(raw) == {}

    def test_it_reads_the_boolean_switches(self, tmp_path):
        raw = {"display": {"scoreboard": {"logos": False, "history": True}}}

        parsed = CutJsonParser(tmp_path / "c").parse_display(raw)

        assert parsed["scoreboard"] == {"logos": False, "history": True}

    def test_it_reads_the_title_card(self, tmp_path):
        raw = {"display": {"title_card": {"background": "blur", "length": 180}}}

        parsed = CutJsonParser(tmp_path / "c").parse_display(raw)

        assert parsed["title_card"] == {"background": "blur", "length": 180}


class TestParseAll:
    def test_it_returns_every_block(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(
            json.dumps(
                {
                    "points": [{"in": 0, "out": 60, "point": "left"}],
                    "overlays": [
                        {
                            "type": "Warning",
                            "warning_type": "replay",
                            "text": "x",
                            "tc": 10,
                        }
                    ],
                    "match": {"start_sides": {"left": "team1", "right": "team2"}},
                    "display": {"scoreboard": {"position": "bottom"}},
                }
            )
        )

        points, overlays, match, display = CutJsonParser(path).parse_all()

        assert len(points) == 1
        assert len(overlays) == 1
        assert match["start_sides"]["left"] == "team1"
        assert display["scoreboard"]["position"] == "bottom"

    def test_an_old_file_still_parses(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"points": [], "overlays": []}))

        _, _, match, display = CutJsonParser(path).parse_all()

        assert (match, display) == ({}, {})
