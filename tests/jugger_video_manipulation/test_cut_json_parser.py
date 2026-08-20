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
        assert self.parser.parse_points(raw) == [
            {"in": 10, "out": 20, "point": "left"}
        ]

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
