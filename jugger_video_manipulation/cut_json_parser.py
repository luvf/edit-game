"""Cut JSON parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

Point = TypedDict(
    "Point",
    {"in": int, "out": int, "point": Literal["left", "right", "nopoint"] | None},
)

Side = Literal["left", "right"]


class WinningCondition(TypedDict):
    """How the match is won."""

    type: Literal["sets", "points", "time"]
    sets_to_win: NotRequired[int]
    points_per_set: NotRequired[int]


class MatchEvent(TypedDict):
    """Something that changes how the score is read, without being drawn.

    A side switch swaps which team the `left` and `right` of a point refer to;
    a set end banks the current score and starts the next set. Neither draws
    anything, which is why they live here and not in `overlays` — encoding a
    switch as a Warning would mean matching on text meant for the screen.
    """

    type: Literal["side_switch", "set_end"]
    tc: int


class Match(TypedDict):
    """The state a scoreboard is computed from.

    No score is stored: it follows from the points, the starting sides and the
    events, so the file cannot contradict itself.
    """

    winning_condition: NotRequired[WinningCondition]
    start_sides: NotRequired[dict[str, str]]
    events: NotRequired[list[MatchEvent]]


class ScoreboardDisplay(TypedDict):
    """How the bar is drawn."""

    position: NotRequired[Literal["top", "bottom"]]
    logos: NotRequired[bool]
    history: NotRequired[bool]


class TitleCardDisplay(TypedDict):
    """How the opening card is drawn."""

    background: NotRequired[Literal["blur", "flat"]]
    length: NotRequired[int]


class Display(TypedDict):
    """Editing choices, as opposed to what happened in the match."""

    scoreboard: NotRequired[ScoreboardDisplay]
    title_card: NotRequired[TitleCardDisplay]


class TeamIntroductionOverlay(TypedDict):
    """Overlay structure for team introduction."""

    type: Literal["TeamIntroduction"]
    team1: str
    team2: str
    condition: str


class WarningOverlay(TypedDict):
    """Overlay structure for warnings."""

    type: Literal["Warning"]
    warning_type: str
    text: str
    tc: int
    length: NotRequired[int]


Overlay = TeamIntroductionOverlay | WarningOverlay


def _as_int(value: Any) -> int | None:
    """Return `value` as an int, or None when it is not one."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CutJsonParser:
    """Parse cut JSON payloads."""

    def __init__(self, cut_json_path: str | Path) -> None:
        """Initialize the parser with a cut JSON file path.

        Args:
            cut_json_path: path to the cut JSON file
        """
        self.cut_json_path = Path(cut_json_path)

    def load(self) -> dict[str, Any]:
        """Load raw cut JSON data or return empty defaults.

        Returns:
            raw JSON data with "points" and "overlays" keys
        """
        if not self.cut_json_path.exists():
            return {"points": [], "overlays": []}
        with self.cut_json_path.open() as f:
            data: dict[str, Any] = json.load(f)
        return data

    def parse_points(self, raw: dict[str, Any]) -> list[Point]:
        """Parse point ranges from raw JSON data.

        Args:
            raw: raw JSON data containing point entries
        Returns:
            parsed list of points
        """
        points = raw.get("points") or []
        parsed: list[Point] = []
        for item in points:
            if not isinstance(item, dict):
                continue
            try:
                in_frame = int(item.get("in", 0))
                out_frame = int(item.get("out", 0))
            except (TypeError, ValueError):
                continue
            point = item.get("point")
            if point not in ("left", "right", "nopoint"):
                point = None
            parsed.append({"in": in_frame, "out": out_frame, "point": point})
        return parsed

    def parse_overlays(self, raw: dict[str, Any]) -> list[Overlay]:
        """Parse overlay entries from raw JSON data.

        Args:
            raw: raw JSON data containing overlay entries
        Returns:
            parsed list of overlays
        """
        overlays = raw.get("overlays") or []
        parsed: list[Overlay] = []
        for item in overlays:
            if not isinstance(item, dict):
                continue
            overlay_type = item.get("type")
            if overlay_type == "TeamIntroduction":
                parsed.append(
                    {
                        "type": "TeamIntroduction",
                        "team1": str(item.get("team1", "")),
                        "team2": str(item.get("team2", "")),
                        "condition": str(item.get("condition", "")),
                    }
                )
            elif overlay_type == "Warning":
                try:
                    tc_value = int(item.get("tc", 0))
                except (TypeError, ValueError):
                    tc_value = 0
                length_value = item.get("length")
                if length_value is not None:
                    try:
                        length_value = int(length_value)
                    except (TypeError, ValueError):
                        length_value = None
                overlay: WarningOverlay = {
                    "type": "Warning",
                    "warning_type": str(item.get("warning_type", "")),
                    "text": str(item.get("text", "")),
                    "tc": tc_value,
                }
                if length_value is not None:
                    overlay["length"] = length_value
                parsed.append(overlay)
        return parsed

    def parse_match(self, raw: dict[str, Any]) -> Match:
        """Parse the match block, which the scoreboard is computed from.

        A file without one renders exactly as it did before, with no
        scoreboard, so the block is optional at every level.

        Args:
            raw: raw JSON data
        Returns:
            the parsed match state, empty when the block is absent
        """
        block = raw.get("match")
        if not isinstance(block, dict):
            return {}

        match: Match = {}

        condition = block.get("winning_condition")
        if isinstance(condition, dict) and condition.get("type") in (
            "sets",
            "points",
            "time",
        ):
            parsed_condition: WinningCondition = {"type": condition["type"]}
            for key in ("sets_to_win", "points_per_set"):
                value = _as_int(condition.get(key))
                if value is not None:
                    parsed_condition[key] = value
            match["winning_condition"] = parsed_condition

        sides = block.get("start_sides")
        if isinstance(sides, dict) and {"left", "right"} <= set(sides):
            match["start_sides"] = {
                "left": str(sides["left"]),
                "right": str(sides["right"]),
            }

        events: list[MatchEvent] = []
        for item in block.get("events") or []:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            tc = _as_int(item.get("tc"))
            if kind in ("side_switch", "set_end") and tc is not None:
                events.append({"type": kind, "tc": tc})
        events.sort(key=lambda event: event["tc"])
        if events:
            match["events"] = events

        return match

    @staticmethod
    def _parse_scoreboard(block: Any) -> ScoreboardDisplay:
        """Parse the scoreboard options of a display block."""
        if not isinstance(block, dict):
            return {}
        parsed: ScoreboardDisplay = {}
        if block.get("position") in ("top", "bottom"):
            parsed["position"] = block["position"]
        for key in ("logos", "history"):
            if isinstance(block.get(key), bool):
                parsed[key] = block[key]
        return parsed

    @staticmethod
    def _parse_title_card(block: Any) -> TitleCardDisplay:
        """Parse the title-card options of a display block."""
        if not isinstance(block, dict):
            return {}
        parsed: TitleCardDisplay = {}
        if block.get("background") in ("blur", "flat"):
            parsed["background"] = block["background"]
        length = _as_int(block.get("length"))
        if length is not None:
            parsed["length"] = length
        return parsed

    def parse_display(self, raw: dict[str, Any]) -> Display:
        """Parse the display block: editing choices, not match facts.

        Args:
            raw: raw JSON data
        Returns:
            the parsed display options, empty when the block is absent
        """
        block = raw.get("display")
        if not isinstance(block, dict):
            return {}

        display: Display = {}
        bar = self._parse_scoreboard(block.get("scoreboard"))
        if bar:
            display["scoreboard"] = bar
        card = self._parse_title_card(block.get("title_card"))
        if card:
            display["title_card"] = card
        return display

    def parse(self) -> tuple[list[Point], list[Overlay]]:
        """Parse points and overlays from the configured JSON file.

        Returns:
            tuple of parsed points and overlays
        """
        raw = self.load()
        return self.parse_points(raw), self.parse_overlays(raw)

    def parse_all(self) -> tuple[list[Point], list[Overlay], Match, Display]:
        """Parse every block in one read.

        Returns:
            points, overlays, match state and display options
        """
        raw = self.load()
        return (
            self.parse_points(raw),
            self.parse_overlays(raw),
            self.parse_match(raw),
            self.parse_display(raw),
        )
