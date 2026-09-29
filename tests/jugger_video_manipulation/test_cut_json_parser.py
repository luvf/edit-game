"""Tests for jugger_video_manipulation.cut_json_parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

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

    def test_it_reads_the_stabilise_switch(self, tmp_path):
        raw = {"display": {"stabilise": True}}

        assert CutJsonParser(tmp_path / "c").parse_display(raw) == {"stabilise": True}

    def test_it_reads_the_intro_and_end_screen_switches(self, tmp_path):
        raw = {"display": {"intro": False, "tail": True}}

        parsed = CutJsonParser(tmp_path / "c").parse_display(raw)

        assert parsed == {"intro": False, "tail": True}

    def test_a_switch_left_out_is_left_out(self, tmp_path):
        # Absent means "the default", decided by the render: not written here.
        assert CutJsonParser(tmp_path / "c").parse_display({"display": {}}) == {}

    def test_a_stabilise_that_is_not_a_boolean_is_dropped(self, tmp_path):
        # "false" as a string is truthy: taking it would stabilise a cut the
        # editor asked not to.
        raw = {"display": {"stabilise": "false"}}

        assert CutJsonParser(tmp_path / "c").parse_display(raw) == {}


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
                    "display": {"scoreboard": {"position": "bottom"}},
                }
            )
        )

        points, overlays, display = CutJsonParser(path).parse_all()

        assert len(points) == 1
        assert len(overlays) == 1
        assert display["scoreboard"]["position"] == "bottom"

    def test_an_old_file_still_parses(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"points": [], "overlays": []}))

        points, overlays, display = CutJsonParser(path).parse_all()

        assert (points, overlays, display) == ([], [], {})


class TestGameInfo:
    """What the match is belongs to the game now, not to the cut file."""

    @pytest.mark.parametrize("kind", ["GameInfo", "TeamIntroduction"])
    def test_an_old_match_block_is_skipped(self, tmp_path, kind):
        raw = {
            "overlays": [
                {"type": kind, "team1": "A", "team2": "B", "sets_to_win": 3},
                {"type": "SideSwitch", "tc": 10},
            ]
        }

        parsed = CutJsonParser(tmp_path / "c").parse_overlays(raw)

        assert parsed == [{"type": "SideSwitch", "tc": 10}]


class TestScoreEventOverlays:
    """Side switches and set ends are edited among the overlays."""

    def test_a_side_switch_keeps_only_its_timecode(self, tmp_path):
        raw = {"overlays": [{"type": "SideSwitch", "tc": 720, "text": "ignoré"}]}

        parsed = CutJsonParser(tmp_path / "c").parse_overlays(raw)

        assert parsed == [{"type": "SideSwitch", "tc": 720}]

    def test_a_set_end_is_parsed(self, tmp_path):
        raw = {"overlays": [{"type": "SetEnd", "tc": 900}]}

        parsed = CutJsonParser(tmp_path / "c").parse_overlays(raw)

        assert parsed == [{"type": "SetEnd", "tc": 900}]

    def test_one_without_a_timecode_is_dropped(self, tmp_path):
        raw = {"overlays": [{"type": "SetEnd"}]}

        assert CutJsonParser(tmp_path / "c").parse_overlays(raw) == []
